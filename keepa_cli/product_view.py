"""
keepa_cli/product_view.py
文件说明：把 Keepa Product Object 转换为 Agent 友好的稳定视图。
主要职责：摘要化 csv/history、stats 位置数组、媒体、A+ 与常用商业字段。
依赖边界：不发起 Keepa 请求；调用方负责提供原始响应与 raw output 元数据。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from keepa_cli.keepa_time import keepa_minutes_to_iso


PRODUCT_VIEW_SCHEMA_VERSION = "2026-05-10.5"

DEFAULT_TEMPORAL_WINDOWS = (7, 30, 90, 180, 365)

TEMPORAL_FEATURE_SERIES = (
    "amazon",
    "new",
    "sales_rank",
    "buy_box_shipping",
    "new_fba",
    "new_offer_count",
    "new_fba_offer_count",
    "rating",
    "review_count",
)

PROFILE_FIELDS = {
    "summary": [
        "identity",
        "category",
        "pricing",
        "demand",
        "rating",
        "temporal_features",
        "selection_signals",
        "data_quality",
        "next_actions",
    ],
    "research": [],
    "deal": [
        "identity",
        "category",
        "pricing",
        "demand",
        "rating",
        "offers",
        "media",
        "aplus",
        "temporal_features",
        "selection_signals",
        "data_quality",
        "next_actions",
        "raw_field_presence",
    ],
    "audit": [
        "identity",
        "data_quality",
        "next_actions",
        "temporal_features",
        "selection_signals",
        "raw_field_presence",
    ],
}

CSV_TYPES: dict[int, dict[str, Any]] = {
    0: {"name": "amazon", "unit": "currency", "is_price": True, "with_shipping": False},
    1: {"name": "new", "unit": "currency", "is_price": True, "with_shipping": False},
    2: {"name": "used", "unit": "currency", "is_price": True, "with_shipping": False},
    3: {"name": "sales_rank", "unit": "rank", "is_price": False, "with_shipping": False},
    4: {"name": "list_price", "unit": "currency", "is_price": True, "with_shipping": False},
    5: {"name": "collectible", "unit": "currency", "is_price": True, "with_shipping": False},
    6: {"name": "refurbished", "unit": "currency", "is_price": True, "with_shipping": False},
    7: {"name": "new_fbm_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    8: {"name": "lightning_deal", "unit": "currency", "is_price": True, "with_shipping": False},
    9: {"name": "warehouse", "unit": "currency", "is_price": True, "with_shipping": False},
    10: {"name": "new_fba", "unit": "currency", "is_price": True, "with_shipping": False},
    11: {"name": "new_offer_count", "unit": "count", "is_price": False, "with_shipping": False},
    12: {"name": "used_offer_count", "unit": "count", "is_price": False, "with_shipping": False},
    13: {"name": "refurbished_offer_count", "unit": "count", "is_price": False, "with_shipping": False},
    14: {"name": "collectible_offer_count", "unit": "count", "is_price": False, "with_shipping": False},
    15: {"name": "extra_info_updates", "unit": "count", "is_price": False, "with_shipping": False},
    16: {"name": "rating", "unit": "rating", "is_price": False, "with_shipping": False},
    17: {"name": "review_count", "unit": "count", "is_price": False, "with_shipping": False},
    18: {"name": "buy_box_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    19: {"name": "used_like_new_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    20: {"name": "used_very_good_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    21: {"name": "used_good_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    22: {"name": "used_acceptable_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    23: {"name": "collectible_like_new_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    24: {"name": "collectible_very_good_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    25: {"name": "collectible_good_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    26: {"name": "collectible_acceptable_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    27: {"name": "refurbished_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    28: {"name": "ebay_new_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    29: {"name": "ebay_used_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    30: {"name": "trade_in", "unit": "currency", "is_price": True, "with_shipping": False},
    31: {"name": "rental", "unit": "currency", "is_price": True, "with_shipping": False},
    32: {"name": "buy_box_used_shipping", "unit": "currency", "is_price": True, "with_shipping": True},
    33: {"name": "prime_exclusive", "unit": "currency", "is_price": True, "with_shipping": False},
    34: {"name": "new_fba_offer_count", "unit": "count", "is_price": False, "with_shipping": False},
    35: {"name": "new_fbm_offer_count", "unit": "count", "is_price": False, "with_shipping": False},
}

BUY_BOX_ELIGIBLE_OFFER_KEYS = [
    "new_fba",
    "new_fbm",
    "used_fba",
    "used_fbm",
    "collectible_fba",
    "collectible_fbm",
    "refurbished_fba",
    "refurbished_fbm",
]


def build_agent_product_view(
    data: Mapping[str, Any],
    *,
    history_limit: int = 10,
    temporal_windows: Any = None,
    media_limit: int = 5,
    view_profile: str = "research",
    fields: Any = None,
    chunks_dir: Path | str | None = None,
) -> dict[str, Any]:
    body = data.get("body")
    source = body if isinstance(body, Mapping) else data
    products = source.get("products") if isinstance(source, Mapping) else None
    product_items = products if isinstance(products, list) else []
    normalized_profile = _normalize_profile(view_profile)
    normalized_fields = _normalize_fields(fields)
    normalized_windows = _normalize_temporal_windows(temporal_windows)
    raw: dict[str, Any] = {
        "body_omitted": True,
        "offline": bool(data.get("offline")),
    }
    if data.get("fixture"):
        raw["fixture"] = data.get("fixture")
    if data.get("output"):
        raw["output"] = data.get("output")

    result: dict[str, Any] = {
        "view": "agent_product",
        "profile": normalized_profile,
        "schema_version": PRODUCT_VIEW_SCHEMA_VERSION,
        "product_count": len(product_items),
        "products": [
            _product_to_agent_view(
                product,
                history_limit=max(0, history_limit),
                temporal_windows=normalized_windows,
                media_limit=max(1, media_limit),
                view_profile=normalized_profile,
                fields=normalized_fields,
            )
            for product in product_items
            if isinstance(product, Mapping)
        ],
        "raw": raw,
        "field_notes": [
            "raw Keepa body is omitted from agent view; use --out to persist the full response",
            "csv/history and stats arrays are mapped by official Keepa CsvType index names",
            "currency values keep raw integer cents plus decimal value for agent safety",
        ],
    }
    if data.get("cache_provenance"):
        result["cache_provenance"] = data.get("cache_provenance")
    if chunks_dir:
        result["chunks"] = write_agent_view_chunks(result, chunks_dir)
    return result


def build_product_compare_view(agent_view: Mapping[str, Any]) -> dict[str, Any]:
    products = agent_view.get("products") if isinstance(agent_view.get("products"), list) else []
    rows: list[dict[str, Any]] = []
    for product in products:
        if not isinstance(product, Mapping):
            continue
        identity = product.get("identity") if isinstance(product.get("identity"), Mapping) else {}
        pricing = product.get("pricing") if isinstance(product.get("pricing"), Mapping) else {}
        demand = product.get("demand") if isinstance(product.get("demand"), Mapping) else {}
        rating = product.get("rating") if isinstance(product.get("rating"), Mapping) else {}
        offers = product.get("offers") if isinstance(product.get("offers"), Mapping) else {}
        media = product.get("media") if isinstance(product.get("media"), Mapping) else {}
        aplus = product.get("aplus") if isinstance(product.get("aplus"), Mapping) else {}
        category = product.get("category") if isinstance(product.get("category"), Mapping) else {}
        current = pricing.get("current") if isinstance(pricing.get("current"), Mapping) else {}
        buy_box = pricing.get("buy_box") if isinstance(pricing.get("buy_box"), Mapping) else {}
        rows.append(
            _compact(
                {
                    "asin": identity.get("asin"),
                    "title": identity.get("title"),
                    "brand": identity.get("brand"),
                    "new_price": _amount_from_value(current.get("new")),
                    "buy_box_price": _amount_from_value(buy_box.get("price") or current.get("buy_box_shipping")),
                    "sales_rank": _plain_value(category.get("sales_rank_current")),
                    "monthly_sold": demand.get("monthly_sold"),
                    "rating": _plain_value(rating.get("rating")),
                    "review_count": _plain_value(rating.get("review_count")),
                    "coupon": pricing.get("coupon"),
                    "total_offer_count": offers.get("total_offer_count"),
                    "video_count": media.get("video_count"),
                    "aplus_available": aplus.get("available"),
                    "selection_signals": product.get("selection_signals"),
                    "risk_flags": (product.get("selection_signals") or {}).get("risk_flags")
                    if isinstance(product.get("selection_signals"), Mapping)
                    else None,
                    "data_quality": product.get("data_quality"),
                }
            )
        )
    return {
        "view": "products_compare",
        "schema_version": PRODUCT_VIEW_SCHEMA_VERSION,
        "product_count": len(rows),
        "rows": rows,
        "source_view": {
            "profile": agent_view.get("profile"),
            "raw": agent_view.get("raw"),
            "chunks": agent_view.get("chunks"),
        },
    }


def write_agent_view_chunks(agent_view: Mapping[str, Any], chunks_dir: Path | str) -> list[dict[str, Any]]:
    output_dir = Path(chunks_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[dict[str, Any]] = []
    products = agent_view.get("products") if isinstance(agent_view.get("products"), list) else []
    for index, product in enumerate(products):
        if not isinstance(product, Mapping):
            continue
        asin = str((product.get("identity") or {}).get("asin") or f"product-{index}")
        for section in (
            "identity",
            "pricing",
            "demand",
            "rating",
            "offers",
            "media",
            "aplus",
            "selection_signals",
            "history_summary",
            "temporal_features",
        ):
            if section not in product:
                continue
            path = output_dir / f"{asin}-{section}.json"
            content = {
                "asin": asin,
                "section": section,
                "schema_version": PRODUCT_VIEW_SCHEMA_VERSION,
                "data": product[section],
            }
            path.write_text(json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            chunks.append({"asin": asin, "name": section, "path": str(path), "format": "json", "size_bytes": path.stat().st_size})
    return chunks


def _product_to_agent_view(
    product: Mapping[str, Any],
    *,
    history_limit: int,
    temporal_windows: tuple[int, ...],
    media_limit: int,
    view_profile: str,
    fields: list[str],
) -> dict[str, Any]:
    stats = product.get("stats") if isinstance(product.get("stats"), Mapping) else {}
    current = stats.get("current") if isinstance(stats, Mapping) else None
    result = {
        "identity": _identity(product),
        "category": _category(product, current),
        "pricing": _pricing(product, stats),
        "demand": _demand(product, stats, history_limit),
        "rating": _rating(product, current),
        "offers": _offers(product, stats),
        "media": _media(product, media_limit),
        "aplus": _aplus(product, media_limit),
        "content": _content(product),
        "compliance_and_logistics": _compliance_and_logistics(product),
        "variations": _variations(product, media_limit),
        "stats_summary": _stats_summary(stats),
        "history_summary": _history_summary(product, history_limit),
        "raw_field_presence": _raw_field_presence(product),
    }
    result["temporal_features"] = _temporal_features(product, windows=temporal_windows)
    result["data_quality"] = _data_quality(product, result)
    result["next_actions"] = _next_actions(result)
    result["selection_signals"] = _selection_signals(result)
    return _filter_product_view(result, view_profile=view_profile, fields=fields)


def _identity(product: Mapping[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "asin": product.get("asin"),
            "title": product.get("title"),
            "brand": product.get("brand"),
            "manufacturer": product.get("manufacturer"),
            "domain_id": product.get("domainId"),
            "type": product.get("type"),
            "product_type": product.get("productType"),
            "product_group": product.get("productGroup"),
            "item_type_keyword": product.get("itemTypeKeyword"),
            "model": product.get("model"),
            "part_number": product.get("partNumber"),
            "url_slug": product.get("urlSlug"),
            "parent_asin": product.get("parentAsin"),
            "is_redirect_asin": product.get("isRedirectASIN"),
            "is_adult_product": product.get("isAdultProduct"),
        }
    )


def _category(product: Mapping[str, Any], current: Any) -> dict[str, Any]:
    rank_value = _stats_value_at(current, 3)
    return _compact(
        {
            "root_category": product.get("rootCategory"),
            "category_ids": product.get("categories"),
            "category_tree": _category_tree(product.get("categoryTree")),
            "sales_rank_reference": product.get("salesRankReference"),
            "sales_rank_display_group": product.get("salesRankDisplayGroup"),
            "sales_rank_current": rank_value,
            "sales_ranks": _sales_ranks(product.get("salesRanks")),
        }
    )


def _pricing(product: Mapping[str, Any], stats: Mapping[str, Any]) -> dict[str, Any]:
    current = stats.get("current")
    price_names = [
        "amazon",
        "new",
        "used",
        "list_price",
        "new_fbm_shipping",
        "warehouse",
        "new_fba",
        "buy_box_shipping",
        "buy_box_used_shipping",
        "prime_exclusive",
    ]
    current_prices = _stats_named_values(current, include_units={"currency"}, names=price_names)
    buy_box = _compact(
        {
            "price": _currency_value(stats.get("buyBoxPrice")),
            "shipping": _currency_value(stats.get("buyBoxShipping")),
            "seller_id": stats.get("buyBoxSellerId"),
            "is_amazon": stats.get("buyBoxIsAmazon"),
            "is_fba": stats.get("buyBoxIsFBA"),
            "is_prime_eligible": stats.get("buyBoxIsPrimeEligible"),
            "is_free_shipping_eligible": stats.get("buyBoxIsFreeShippingEligible"),
            "saving_basis": _currency_value(stats.get("buyBoxSavingBasis")),
            "saving_basis_type": stats.get("buyBoxSavingBasisType"),
            "saving_percentage": stats.get("buyBoxSavingPercentage"),
            "condition": stats.get("buyBoxCondition"),
            "availability_message": stats.get("buyBoxAvailabilityMessage"),
        }
    )
    return _compact(
        {
            "current": current_prices,
            "avg30": _stats_named_values(stats.get("avg30"), include_units={"currency"}, names=price_names),
            "avg90": _stats_named_values(stats.get("avg90"), include_units={"currency"}, names=price_names),
            "avg180": _stats_named_values(stats.get("avg180"), include_units={"currency"}, names=price_names),
            "trade_in_price": _currency_value(stats.get("tradeInPrice")),
            "competitive_price_threshold": _currency_value(product.get("competitivePriceThreshold")),
            "coupon": product.get("coupon"),
            "coupon_history": _history_pairs(product.get("couponHistory"), history_limit=5),
            "promotions": _limit_list(product.get("promotions"), 5),
            "buy_box": buy_box,
        }
    )


def _demand(product: Mapping[str, Any], stats: Mapping[str, Any], history_limit: int) -> dict[str, Any]:
    return _compact(
        {
            "monthly_sold": product.get("monthlySold"),
            "monthly_sold_history": _history_pairs(product.get("monthlySoldHistory"), history_limit=history_limit),
            "sales_rank_drops": _compact(
                {
                    "30": stats.get("salesRankDrops30"),
                    "90": stats.get("salesRankDrops90"),
                    "180": stats.get("salesRankDrops180"),
                    "365": stats.get("salesRankDrops365"),
                }
            ),
            "delta_percent_90_monthly_sold": stats.get("deltaPercent90_monthlySold"),
            "listed_since": _time_field(product.get("listedSince")),
            "tracking_since": _time_field(product.get("trackingSince")),
            "last_sold_update": _time_field(product.get("lastSoldUpdate")),
        }
    )


def _rating(product: Mapping[str, Any], current: Any) -> dict[str, Any]:
    rating = _stats_value_at(current, 16)
    reviews = _stats_value_at(current, 17)
    return _compact(
        {
            "rating": rating,
            "review_count": reviews,
            "has_reviews": product.get("hasReviews"),
            "last_rating_update": _time_field(product.get("lastRatingUpdate")),
            "reviews_object_available": isinstance(product.get("reviews"), Mapping),
        }
    )


def _offers(product: Mapping[str, Any], stats: Mapping[str, Any]) -> dict[str, Any]:
    out_of_stock_names = ["amazon", "new", "used", "lightning_deal", "prime_exclusive"]
    return _compact(
        {
            "total_offer_count": _missing_if_negative(stats.get("totalOfferCount")),
            "retrieved_offer_count": _missing_if_negative(stats.get("retrievedOfferCount")),
            "offer_count_fba": _missing_if_negative(stats.get("offerCountFBA")),
            "offer_count_fbm": _missing_if_negative(stats.get("offerCountFBM")),
            "buy_box_eligible_offer_counts": _map_fixed_list(
                product.get("buyBoxEligibleOfferCounts"),
                BUY_BOX_ELIGIBLE_OFFER_KEYS,
            ),
            "offers_successful": product.get("offersSuccessful"),
            "live_offers_count": len(product.get("liveOffersOrder") or [])
            if isinstance(product.get("liveOffersOrder"), list)
            else None,
            "out_of_stock_percentage": _compact(
                {
                    "30": _stats_percent_values(stats.get("outOfStockPercentage30"), names=out_of_stock_names),
                    "90": _stats_percent_values(stats.get("outOfStockPercentage90"), names=out_of_stock_names),
                    "180": _stats_percent_values(stats.get("outOfStockPercentage180"), names=out_of_stock_names),
                    "365": _stats_percent_values(stats.get("outOfStockPercentage365"), names=out_of_stock_names),
                }
            ),
            "lowest_fba_seller_ids": _limit_list(stats.get("sellerIdsLowestFBA"), 5),
            "lowest_fbm_seller_ids": _limit_list(stats.get("sellerIdsLowestFBM"), 5),
        }
    )


def _media(product: Mapping[str, Any], media_limit: int) -> dict[str, Any]:
    images = _image_samples(product.get("images"), media_limit)
    videos = _video_samples(product.get("videos"), media_limit)
    return _compact(
        {
            "image_count": _safe_len(product.get("images")),
            "images": images,
            "video_count": _safe_len(product.get("videos")),
            "videos": videos,
        }
    )


def _aplus(product: Mapping[str, Any], media_limit: int) -> dict[str, Any]:
    blocks = product.get("aPlus")
    if not isinstance(blocks, list):
        return {"available": False}
    modules: list[Mapping[str, Any]] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        raw_modules = block.get("module") or block.get("modules")
        if isinstance(raw_modules, list):
            modules.extend(item for item in raw_modules if isinstance(item, Mapping))
    images: list[Any] = []
    videos: list[Any] = []
    alt_text: list[Any] = []
    text_samples: list[str] = []
    for module in modules:
        images.extend(_as_list(module.get("image")))
        videos.extend(_as_list(module.get("video")))
        alt_text.extend(_as_list(module.get("imageAltText")))
        text_samples.extend(str(item) for item in _as_list(module.get("text")) if item)
    return _compact(
        {
            "available": True,
            "block_count": len(blocks),
            "module_count": len(modules),
            "image_count": len(images),
            "video_count": len(videos),
            "images": [_media_url(item) for item in images[:media_limit]],
            "image_alt_text": alt_text[:media_limit],
            "text_samples": [_truncate_text(item, 240) for item in text_samples[:media_limit]],
        }
    )


def _content(product: Mapping[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "features": _limit_list(product.get("features"), 12),
            "description": _truncate_text(product.get("description"), 1000),
            "ingredients": _truncate_text(product.get("ingredients"), 1000),
            "active_ingredients": _limit_list(product.get("activeIngredients"), 12),
            "special_ingredients": _limit_list(product.get("specialIngredients"), 12),
            "safety_warning": _truncate_text(product.get("safetyWarning"), 500),
            "product_benefit": _truncate_text(product.get("productBenefit"), 500),
            "recommended_uses_for_product": _limit_list(product.get("recommendedUsesForProduct"), 12),
            "target_audience_keyword": _limit_list(product.get("targetAudienceKeyword"), 12),
            "size": product.get("size"),
            "scent": product.get("scent"),
            "color": product.get("color"),
            "item_form": product.get("itemForm"),
            "binding": product.get("binding"),
            "languages": product.get("languages"),
        }
    )


def _compliance_and_logistics(product: Mapping[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "is_heat_sensitive": product.get("isHeatSensitive"),
            "is_eligible_for_super_saver_shipping": product.get("isEligibleForSuperSaverShipping"),
            "is_eligible_for_trade_in": product.get("isEligibleForTradeIn"),
            "package": _compact(
                {
                    "length": product.get("packageLength"),
                    "width": product.get("packageWidth"),
                    "height": product.get("packageHeight"),
                    "weight": product.get("packageWeight"),
                    "quantity": product.get("packageQuantity"),
                }
            ),
            "item": _compact(
                {
                    "length": product.get("itemLength"),
                    "width": product.get("itemWidth"),
                    "height": product.get("itemHeight"),
                    "weight": product.get("itemWeight"),
                }
            ),
            "fba_fees": product.get("fbaFees"),
            "referral_fee_percent": product.get("referralFeePercent"),
            "referral_fee_percentage": product.get("referralFeePercentage"),
            "unit_count": product.get("unitCount"),
        }
    )


def _variations(product: Mapping[str, Any], media_limit: int) -> dict[str, Any]:
    variations = product.get("variations")
    return _compact(
        {
            "parent_asin": product.get("parentAsin"),
            "variation_count": _safe_len(variations),
            "sample": _limit_list(variations, media_limit),
            "parent_asin_history": _history_pairs(product.get("parentAsinHistory"), history_limit=media_limit),
        }
    )


def _stats_summary(stats: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(stats, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in ("current", "avg", "avg30", "avg90", "avg180", "avg365"):
        values = _stats_named_values(stats.get(key))
        if values:
            result[key] = values
    ranges: dict[str, Any] = {}
    for key in ("min", "max", "minInInterval", "maxInInterval"):
        values = _stats_range_values(stats.get(key))
        if values:
            ranges[key] = values
    if ranges:
        result["ranges"] = ranges
    return result


def _history_summary(product: Mapping[str, Any], history_limit: int) -> dict[str, Any]:
    csv_history = product.get("csv")
    if not isinstance(csv_history, list):
        return {"available": False}
    series: dict[str, Any] = {}
    warnings: list[str] = []
    for index, raw_values in enumerate(csv_history):
        if not raw_values:
            continue
        meta = CSV_TYPES.get(index, _unknown_csv_type(index))
        if not isinstance(raw_values, list):
            warnings.append(f"csv[{index}] is not a list")
            continue
        points, warning = _parse_csv_points(raw_values, meta)
        if warning:
            warnings.append(warning)
        if not points:
            continue
        present_values = [point["value"] for point in points if point.get("value") is not None]
        series[str(meta["name"])] = _compact(
            {
                "index": index,
                "unit": meta["unit"],
                "point_count": len(points),
                "first": points[0],
                "latest": points[-1],
                "min_value": min(present_values) if present_values else None,
                "max_value": max(present_values) if present_values else None,
                "last_points": points[-history_limit:] if history_limit else [],
                "omitted_points": max(0, len(points) - history_limit),
            }
        )
    return _compact(
        {
            "available": True,
            "series_count": len(series),
            "series": series,
            "warnings": warnings,
        }
    )


def _temporal_features(product: Mapping[str, Any], *, windows: tuple[int, ...]) -> dict[str, Any]:
    csv_history = product.get("csv")
    if not isinstance(csv_history, list):
        return {"available": False}
    requested = set(TEMPORAL_FEATURE_SERIES)
    series: dict[str, Any] = {}
    warnings: list[str] = []
    for index, raw_values in enumerate(csv_history):
        meta = CSV_TYPES.get(index, _unknown_csv_type(index))
        name = str(meta["name"])
        if name not in requested or not raw_values:
            continue
        if not isinstance(raw_values, list):
            warnings.append(f"csv[{index}] is not a list")
            continue
        points, warning = _parse_csv_points(raw_values, meta)
        if warning:
            warnings.append(warning)
        features = _series_temporal_features(name=name, unit=str(meta["unit"]), points=points, windows=windows)
        if features:
            series[name] = features
    if not series:
        warnings.append("no supported temporal series with at least two numeric points")
    return _compact(
        {
            "available": bool(series),
            "series_count": len(series),
            "windows_days": list(windows),
            "series": series,
            "warnings": warnings,
        }
    )


def _series_temporal_features(
    *,
    name: str,
    unit: str,
    points: list[dict[str, Any]],
    windows: tuple[int, ...],
) -> dict[str, Any]:
    points = _numeric_points(points)
    if len(points) < 2:
        return {}
    values = [float(point["value"]) for point in points]
    keepa_minutes = [int(point["keepa_minute"]) for point in points]
    first = points[0]
    latest = points[-1]
    change = float(latest["value"]) - float(first["value"])
    previous_change = float(latest["value"]) - float(points[-2]["value"])
    duration_days = max(0.0, (keepa_minutes[-1] - keepa_minutes[0]) / 1440)
    mean_value = sum(values) / len(values)
    min_value = min(values)
    max_value = max(values)
    volatility = _coefficient_of_variation(values)
    deltas = [values[index] - values[index - 1] for index in range(1, len(values))]
    window_features = {
        f"recent_{days}d": window
        for days in windows
        if (window := _window_change(points, days=days)) is not None
    }
    return _compact(
        {
            "unit": unit,
            "name": name,
            "point_count": len(points),
            "duration_days": round(duration_days, 3),
            "sampling": _sampling_features(keepa_minutes),
            "first_value": _round_metric(float(first["value"])),
            "latest_value": _round_metric(float(latest["value"])),
            "previous_value": _round_metric(float(points[-2]["value"])),
            "change_abs": _round_metric(change),
            "change_pct": _pct_change(float(first["value"]), float(latest["value"])),
            "previous_change_abs": _round_metric(previous_change),
            "previous_change_pct": _pct_change(float(points[-2]["value"]), float(latest["value"])),
            "min_value": _round_metric(min_value),
            "max_value": _round_metric(max_value),
            "range_abs": _round_metric(max_value - min_value),
            "range_pct_of_mean": _ratio_pct(max_value - min_value, mean_value),
            "mean_value": _round_metric(mean_value),
            "median_value": _round_metric(_percentile(values, 0.5)),
            "latest_percentile": _latest_percentile(values),
            "latest_zscore": _zscore(values, float(latest["value"])),
            "volatility_cv": volatility,
            "dispersion": _dispersion_features(values),
            "change_profile": _change_profile(deltas),
            "outliers": _outlier_features(values),
            "shape": _shape_features(values),
            "trend_direction": _trend_direction(change),
            "slope_per_day": _slope_per_day(change, duration_days),
            "windows": window_features,
            **window_features,
        }
    )


def _numeric_points(raw_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for candidate in raw_points:
        point_value = candidate.get("value")
        keepa_minute = candidate.get("keepa_minute")
        if not isinstance(point_value, (int, float)) or not isinstance(keepa_minute, int):
            continue
        points.append(
            {
                "timestamp": candidate.get("timestamp"),
                "keepa_minute": keepa_minute,
                "value": point_value,
            }
        )
    deduped: dict[int, dict[str, Any]] = {}
    for point in points:
        deduped[int(point["keepa_minute"])] = point
    return [deduped[key] for key in sorted(deduped)]


def _window_change(points: list[dict[str, Any]], *, days: int) -> dict[str, Any] | None:
    if len(points) < 2:
        return None
    latest = points[-1]
    cutoff = int(latest["keepa_minute"]) - days * 1440
    baseline = points[0]
    for point in points:
        if int(point["keepa_minute"]) >= cutoff:
            baseline = point
            break
    if baseline is latest:
        return None
    change = float(latest["value"]) - float(baseline["value"])
    return _compact(
        {
            "baseline_timestamp": baseline.get("timestamp"),
            "latest_timestamp": latest.get("timestamp"),
            "observed_days": round((int(latest["keepa_minute"]) - int(baseline["keepa_minute"])) / 1440, 3),
            "baseline_value": _round_metric(float(baseline["value"])),
            "latest_value": _round_metric(float(latest["value"])),
            "change_abs": _round_metric(change),
            "change_pct": _pct_change(float(baseline["value"]), float(latest["value"])),
            "trend_direction": _trend_direction(change),
        }
    )


def _coefficient_of_variation(values: list[float]) -> float | None:
    if not values:
        return None
    mean_value = sum(values) / len(values)
    if mean_value == 0:
        return None
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return round((variance**0.5) / abs(mean_value), 4)


def _sampling_features(keepa_minutes: list[int]) -> dict[str, Any]:
    if len(keepa_minutes) < 2:
        return {}
    intervals = [(keepa_minutes[index] - keepa_minutes[index - 1]) / 1440 for index in range(1, len(keepa_minutes))]
    duration_days = max(0.0, (keepa_minutes[-1] - keepa_minutes[0]) / 1440)
    return _compact(
        {
            "avg_interval_days": _round_metric(sum(intervals) / len(intervals)),
            "median_interval_days": _round_metric(_percentile(intervals, 0.5)),
            "max_gap_days": _round_metric(max(intervals)),
            "points_per_30d": _round_metric((len(keepa_minutes) / duration_days) * 30) if duration_days > 0 else None,
        }
    )


def _dispersion_features(values: list[float]) -> dict[str, Any]:
    if not values:
        return {}
    q1 = _percentile(values, 0.25)
    median = _percentile(values, 0.5)
    q3 = _percentile(values, 0.75)
    absolute_deviations = [abs(value - median) for value in values]
    mad = _percentile(absolute_deviations, 0.5)
    return _compact(
        {
            "q1": _round_metric(q1),
            "median": _round_metric(median),
            "q3": _round_metric(q3),
            "iqr": _round_metric(q3 - q1),
            "mad": _round_metric(mad),
        }
    )


def _change_profile(deltas: list[float]) -> dict[str, Any]:
    if not deltas:
        return {}
    up = len([delta for delta in deltas if delta > 0])
    down = len([delta for delta in deltas if delta < 0])
    flat = len(deltas) - up - down
    abs_deltas = [abs(delta) for delta in deltas]
    return _compact(
        {
            "up_steps": up,
            "down_steps": down,
            "flat_steps": flat,
            "direction_change_count": _direction_change_count(deltas),
            "avg_abs_step": _round_metric(sum(abs_deltas) / len(abs_deltas)),
            "max_abs_step": _round_metric(max(abs_deltas)),
            "last_step": _round_metric(deltas[-1]),
        }
    )


def _outlier_features(values: list[float]) -> dict[str, Any]:
    if len(values) < 4:
        return {}
    median = _percentile(values, 0.5)
    deviations = [abs(value - median) for value in values]
    mad = _percentile(deviations, 0.5)
    if mad == 0:
        return {"method": "mad", "count": 0}
    threshold = 3 * 1.4826 * mad
    indexes = [index for index, value in enumerate(values) if abs(value - median) > threshold]
    return _compact(
        {
            "method": "mad",
            "threshold": _round_metric(threshold),
            "count": len(indexes),
            "ratio": _round_metric(len(indexes) / len(values)),
        }
    )


def _shape_features(values: list[float]) -> dict[str, Any]:
    if len(values) < 2:
        return {}
    latest = values[-1]
    max_drawdown = 0.0
    peak = values[0]
    for value in values:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value - peak)
    max_runup = 0.0
    trough = values[0]
    for value in values:
        trough = min(trough, value)
        max_runup = max(max_runup, value - trough)
    return _compact(
        {
            "latest_vs_min_pct": _pct_change(min(values), latest),
            "latest_vs_max_pct": _pct_change(max(values), latest),
            "max_drawdown_abs": _round_metric(max_drawdown),
            "max_runup_abs": _round_metric(max_runup),
            "longest_up_streak": _longest_streak(values, direction="up"),
            "longest_down_streak": _longest_streak(values, direction="down"),
        }
    )


def _direction_change_count(deltas: list[float]) -> int:
    previous = 0
    count = 0
    for delta in deltas:
        current = 1 if delta > 0 else -1 if delta < 0 else 0
        if current == 0:
            continue
        if previous and current != previous:
            count += 1
        previous = current
    return count


def _longest_streak(values: list[float], *, direction: str) -> int:
    longest = 0
    current = 0
    for index in range(1, len(values)):
        delta = values[index] - values[index - 1]
        matches = delta > 0 if direction == "up" else delta < 0
        if matches:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _latest_percentile(values: list[float]) -> float | None:
    if not values:
        return None
    latest = values[-1]
    below_or_equal = len([value for value in values if value <= latest])
    return _round_metric(below_or_equal / len(values))


def _zscore(values: list[float], value: float) -> float | None:
    if len(values) < 2:
        return None
    mean_value = sum(values) / len(values)
    variance = sum((item - mean_value) ** 2 for item in values) / len(values)
    if variance == 0:
        return None
    return _round_metric((value - mean_value) / (variance**0.5))


def _pct_change(first: float, latest: float) -> float | None:
    if first == 0:
        return None
    return round(((latest - first) / abs(first)) * 100, 4)


def _ratio_pct(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return round((numerator / abs(denominator)) * 100, 4)


def _slope_per_day(change: float, duration_days: float) -> float | None:
    if duration_days <= 0:
        return None
    return _round_metric(change / duration_days)


def _trend_direction(change: float) -> str:
    if change > 0:
        return "up"
    if change < 0:
        return "down"
    return "flat"


def _round_metric(value: float) -> float:
    rounded = round(value, 4)
    if rounded == -0.0:
        return 0.0
    return rounded


def _parse_csv_points(values: list[Any], meta: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    group_size = 3 if meta.get("with_shipping") else 2
    warning = None
    if len(values) % group_size != 0:
        warning = f"csv[{meta.get('name')}] length is not divisible by {group_size}"
    points: list[dict[str, Any]] = []
    for offset in range(0, len(values) - group_size + 1, group_size):
        keepa_minute = values[offset]
        raw_value = values[offset + 1]
        raw_shipping = values[offset + 2] if group_size == 3 else None
        if _is_missing_raw_value(raw_value):
            value = None
        else:
            value = _convert_raw_value(raw_value, meta)
        point = {
            "timestamp": keepa_minutes_to_iso(keepa_minute),
            "keepa_minute": int(keepa_minute),
            "value": value,
            "raw_value": raw_value,
        }
        if group_size == 3:
            point["shipping"] = _currency_decimal(raw_shipping)
            point["raw_shipping"] = raw_shipping
        points.append(point)
    return points, warning


def _stats_named_values(
    values: Any,
    *,
    include_units: set[str] | None = None,
    names: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(values, list):
        return {}
    allowed_names = set(names or [])
    result: dict[str, Any] = {}
    for index, raw_value in enumerate(values):
        meta = CSV_TYPES.get(index, _unknown_csv_type(index))
        if include_units is not None and str(meta["unit"]) not in include_units:
            continue
        if allowed_names and str(meta["name"]) not in allowed_names:
            continue
        value = _value_object(raw_value, meta)
        if value is not None:
            result[str(meta["name"])] = value
    return result


def _stats_percent_values(values: Any, *, names: list[str]) -> dict[str, Any]:
    if not isinstance(values, list):
        return {}
    allowed_names = set(names)
    result: dict[str, Any] = {}
    for index, raw_value in enumerate(values):
        meta = CSV_TYPES.get(index, _unknown_csv_type(index))
        name = str(meta["name"])
        if name not in allowed_names or _is_missing_raw_value(raw_value):
            continue
        result[name] = {"value": int(raw_value), "raw_value": raw_value, "unit": "percent"}
    return result


def _stats_range_values(values: Any) -> dict[str, Any]:
    if not isinstance(values, list):
        return {}
    result: dict[str, Any] = {}
    for index, raw_value in enumerate(values):
        if not isinstance(raw_value, list) or len(raw_value) < 2:
            continue
        meta = CSV_TYPES.get(index, _unknown_csv_type(index))
        value = _value_object(raw_value[1], meta)
        if value is None:
            continue
        result[str(meta["name"])] = {
            **value,
            "keepa_minute": raw_value[0],
            "timestamp": keepa_minutes_to_iso(raw_value[0]),
        }
    return result


def _value_object(raw_value: Any, meta: Mapping[str, Any]) -> dict[str, Any] | None:
    if _is_missing_raw_value(raw_value):
        return None
    value = _convert_raw_value(raw_value, meta)
    result = {"value": value, "raw_value": raw_value, "unit": meta["unit"]}
    if meta.get("unit") == "currency":
        result["amount"] = value
        result["currency_value"] = value
    return result


def _stats_value_at(values: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(values, list) or index >= len(values):
        return None
    return _value_object(values[index], CSV_TYPES[index])


def _convert_raw_value(raw_value: Any, meta: Mapping[str, Any]) -> float | int:
    if meta.get("unit") == "currency":
        return _currency_decimal(raw_value)
    if meta.get("unit") == "rating":
        return round(int(raw_value) / 10, 1)
    return int(raw_value)


def _currency_value(raw_value: Any) -> dict[str, Any] | None:
    if _is_missing_raw_value(raw_value):
        return None
    return {"amount": _currency_decimal(raw_value), "raw_value": raw_value, "unit": "currency"}


def _currency_decimal(raw_value: Any) -> float:
    return round(int(raw_value) / 100, 2)


def _is_missing_raw_value(value: Any) -> bool:
    return value is None or (isinstance(value, (int, float)) and value < 0)


def _history_pairs(values: Any, *, history_limit: int) -> dict[str, Any] | None:
    if not isinstance(values, list):
        return None
    points: list[dict[str, Any]] = []
    for offset in range(0, len(values) - 1, 2):
        points.append(
            {
                "timestamp": keepa_minutes_to_iso(values[offset]),
                "keepa_minute": int(values[offset]),
                "value": values[offset + 1],
            }
        )
    return {
        "point_count": len(points),
        "latest": points[-1] if points else None,
        "last_points": points[-history_limit:] if history_limit else [],
        "omitted_points": max(0, len(points) - history_limit),
    }


def _category_tree(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, Mapping):
            result.append(_compact({"id": item.get("catId") or item.get("id"), "name": item.get("name")}))
    return result


def _sales_ranks(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key, raw_values in value.items():
        if not isinstance(raw_values, list) or len(raw_values) < 2:
            continue
        result[str(key)] = _history_pairs(raw_values, history_limit=3)
    return result


def _image_samples(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    samples: list[dict[str, Any]] = []
    for item in value[:limit]:
        if isinstance(item, Mapping):
            samples.append(
                _compact(
                    {
                        "large": _media_url(item.get("l")),
                        "medium": _media_url(item.get("m")),
                        "large_width": item.get("lW"),
                        "large_height": item.get("lH"),
                    }
                )
            )
        else:
            samples.append({"url": _media_url(item)})
    return samples


def _video_samples(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    samples: list[dict[str, Any]] = []
    for item in value[:limit]:
        if isinstance(item, Mapping):
            samples.append(
                _compact(
                    {
                        "title": item.get("title"),
                        "url": item.get("url"),
                        "image": _media_url(item.get("image")),
                        "duration_seconds": item.get("duration"),
                        "creator": item.get("creator"),
                    }
                )
            )
    return samples


def _media_url(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if text.startswith(("http://", "https://")):
        return text
    return f"https://m.media-amazon.com/images/I/{text}"


def _raw_field_presence(product: Mapping[str, Any]) -> dict[str, Any]:
    keys = [
        "csv",
        "stats",
        "images",
        "videos",
        "aPlus",
        "offers",
        "liveOffersOrder",
        "buyBoxSellerIdHistory",
        "couponHistory",
        "monthlySoldHistory",
        "variations",
        "reviews",
    ]
    return {key: key in product and product.get(key) is not None for key in keys}


def _data_quality(product: Mapping[str, Any], view: Mapping[str, Any]) -> dict[str, Any]:
    raw_presence = view.get("raw_field_presence") if isinstance(view.get("raw_field_presence"), Mapping) else {}
    present = [key for key, value in raw_presence.items() if value]
    missing = [key for key, value in raw_presence.items() if not value]
    pricing = view.get("pricing") if isinstance(view.get("pricing"), Mapping) else {}
    demand = view.get("demand") if isinstance(view.get("demand"), Mapping) else {}
    rating = view.get("rating") if isinstance(view.get("rating"), Mapping) else {}
    offers = view.get("offers") if isinstance(view.get("offers"), Mapping) else {}
    aplus = view.get("aplus") if isinstance(view.get("aplus"), Mapping) else {}
    next_missing: list[str] = []
    if not (pricing.get("current") or pricing.get("buy_box")):
        next_missing.append("pricing.current")
    if demand.get("monthly_sold") is None and not demand.get("sales_rank_drops"):
        next_missing.append("demand.monthly_sold")
    if not rating.get("rating"):
        next_missing.append("rating.rating")
    if not raw_presence.get("offers"):
        next_missing.append("offers.offers")
    if not aplus.get("available"):
        next_missing.append("aplus")
    if "csv" not in present:
        next_missing.append("history.csv")
    evidence_count = len(present) + len([item for item in ("pricing.current", "demand.monthly_sold", "rating.rating") if item not in next_missing])
    confidence = "high" if evidence_count >= 7 and not next_missing[:2] else "medium" if evidence_count >= 4 else "low"
    return {
        "present": sorted(set(present)),
        "missing": sorted(set(missing + next_missing)),
        "confidence": confidence,
        "notes": _data_quality_notes(product, view, next_missing),
    }


def _data_quality_notes(product: Mapping[str, Any], view: Mapping[str, Any], missing: list[str]) -> list[str]:
    notes: list[str] = []
    if missing:
        notes.append("some agent-relevant fields are absent or not requested")
    if product.get("offers") is None and product.get("liveOffersOrder") is None:
        notes.append("offer detail usually requires an explicit --offers request")
    if (view.get("history_summary") or {}).get("available") is not True:
        notes.append("history summary is unavailable because raw csv history is absent")
    return notes


def _next_actions(view: Mapping[str, Any]) -> list[dict[str, Any]]:
    identity = view.get("identity") if isinstance(view.get("identity"), Mapping) else {}
    asin = identity.get("asin") or "<ASIN>"
    domain = "<DOMAIN>"
    quality = view.get("data_quality") if isinstance(view.get("data_quality"), Mapping) else {}
    missing = set(quality.get("missing") or [])
    actions: list[dict[str, Any]] = []
    if "offers.offers" in missing:
        actions.append(
            {
                "command": f"products get {asin} --domain {domain} --full --offers 20 --agent-view --view deal",
                "reason": "offer detail is missing; request one offer page only if seller-level competition matters",
                "estimated_tokens": 6,
            }
        )
    if "rating.rating" in missing:
        actions.append(
            {
                "command": f"products get {asin} --domain {domain} --full --rating 1 --agent-view --view research",
                "reason": "rating or review count is missing",
                "estimated_tokens": 1,
            }
        )
    if "aplus" in missing:
        actions.append(
            {
                "command": f"products get {asin} --domain {domain} --full --aplus 1 --agent-view --view research",
                "reason": "A+ content is missing; useful for content-quality checks",
                "estimated_tokens": 1,
            }
        )
    if "history.csv" in missing:
        actions.append(
            {
                "command": f"products get {asin} --domain {domain} --history 1 --stats 180 --agent-view --view research",
                "reason": "history is missing; needed for price and rank stability",
                "estimated_tokens": 1,
            }
        )
    return actions


def _selection_signals(view: Mapping[str, Any]) -> dict[str, Any]:
    pricing = view.get("pricing") if isinstance(view.get("pricing"), Mapping) else {}
    demand = view.get("demand") if isinstance(view.get("demand"), Mapping) else {}
    rating = view.get("rating") if isinstance(view.get("rating"), Mapping) else {}
    offers = view.get("offers") if isinstance(view.get("offers"), Mapping) else {}
    media = view.get("media") if isinstance(view.get("media"), Mapping) else {}
    aplus = view.get("aplus") if isinstance(view.get("aplus"), Mapping) else {}
    category = view.get("category") if isinstance(view.get("category"), Mapping) else {}
    temporal = view.get("temporal_features") if isinstance(view.get("temporal_features"), Mapping) else {}
    temporal_series = temporal.get("series") if isinstance(temporal.get("series"), Mapping) else {}
    new_temporal = temporal_series.get("new") if isinstance(temporal_series.get("new"), Mapping) else {}
    rank_temporal = temporal_series.get("sales_rank") if isinstance(temporal_series.get("sales_rank"), Mapping) else {}
    current = pricing.get("current") if isinstance(pricing.get("current"), Mapping) else {}
    risk_flags: list[str] = []
    monthly_sold = demand.get("monthly_sold")
    review_count = _plain_value(rating.get("review_count"))
    rating_value = _plain_value(rating.get("rating"))
    offer_count = offers.get("total_offer_count")
    if monthly_sold is None:
        risk_flags.append("missing_monthly_sold")
    if rating_value is None:
        risk_flags.append("missing_rating")
    elif rating_value < 4.0:
        risk_flags.append("rating_below_4")
    if review_count is None:
        risk_flags.append("missing_review_count")
    if offer_count is None:
        risk_flags.append("missing_offer_detail")
    elif offer_count > 20:
        risk_flags.append("high_offer_competition")
    if not aplus.get("available"):
        risk_flags.append("missing_aplus")
    if not media.get("video_count"):
        risk_flags.append("missing_video")
    return {
        "demand": _compact(
            {
                "monthly_sold": monthly_sold,
                "sales_rank": _plain_value(category.get("sales_rank_current")),
                "sales_rank_drops": demand.get("sales_rank_drops"),
            }
        ),
        "competition": _compact(
            {
                "total_offer_count": offer_count,
                "retrieved_offer_count": offers.get("retrieved_offer_count"),
                "offer_count_fba": offers.get("offer_count_fba"),
                "offer_count_fbm": offers.get("offer_count_fbm"),
            }
        ),
        "price_stability": _compact(
            {
                "current_new": _amount_from_value(current.get("new")),
                "current_buy_box": _amount_from_value((pricing.get("buy_box") or {}).get("price") if isinstance(pricing.get("buy_box"), Mapping) else None),
                "coupon": pricing.get("coupon"),
                "new_price_change_pct": new_temporal.get("change_pct"),
                "new_price_volatility_cv": new_temporal.get("volatility_cv"),
                "new_price_trend": new_temporal.get("trend_direction"),
                "sales_rank_change_pct": rank_temporal.get("change_pct"),
                "sales_rank_trend": rank_temporal.get("trend_direction"),
                "history_series": (view.get("history_summary") or {}).get("series_count")
                if isinstance(view.get("history_summary"), Mapping)
                else None,
            }
        ),
        "content_quality": _compact(
            {
                "image_count": media.get("image_count"),
                "video_count": media.get("video_count"),
                "aplus_available": aplus.get("available"),
                "aplus_module_count": aplus.get("module_count"),
            }
        ),
        "risk_flags": risk_flags,
    }


def _filter_product_view(result: dict[str, Any], *, view_profile: str, fields: list[str]) -> dict[str, Any]:
    if fields:
        selected = fields
    else:
        selected = PROFILE_FIELDS.get(view_profile, PROFILE_FIELDS["research"])
    if not selected:
        return result
    required = {"identity"}
    selected_set = set(selected) | required
    return {key: value for key, value in result.items() if key in selected_set}


def _normalize_profile(value: str) -> str:
    profile = (value or "research").strip().lower()
    if profile in {"agent", "raw"}:
        return "research"
    if profile not in PROFILE_FIELDS:
        return "research"
    return profile


def _normalize_fields(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = []
        for item in value:
            raw_items.extend(str(item).split(","))
    else:
        raw_items = [str(value)]
    return [item.strip() for item in raw_items if item.strip()]


def _normalize_temporal_windows(value: Any) -> tuple[int, ...]:
    if value in (None, ""):
        return DEFAULT_TEMPORAL_WINDOWS
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = []
        for item in value:
            raw_items.extend(str(item).split(","))
    else:
        raw_items = [str(value)]
    windows: list[int] = []
    for item in raw_items:
        try:
            days = int(str(item).strip())
        except ValueError:
            continue
        if days > 0:
            windows.append(days)
    return tuple(sorted(set(windows))) or DEFAULT_TEMPORAL_WINDOWS


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get("value")
    return value


def _amount_from_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get("amount") or value.get("currency_value") or value.get("value")
    return value


def _map_fixed_list(value: Any, keys: list[str]) -> dict[str, Any]:
    if not isinstance(value, list):
        return {}
    return {
        key: normalized
        for index, key in enumerate(keys)
        if index < len(value) and (normalized := _missing_if_negative(value[index])) is not None
    }


def _missing_if_negative(value: Any) -> Any:
    if isinstance(value, (int, float)) and value < 0:
        return None
    return value


def _time_field(value: Any) -> dict[str, Any] | None:
    if value in (None, 0, -1):
        return None
    return {"keepa_minute": int(value), "timestamp": keepa_minutes_to_iso(value)}


def _truncate_text(value: Any, limit: int) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def _limit_list(value: Any, limit: int) -> list[Any]:
    if isinstance(value, list):
        return value[:limit]
    if isinstance(value, tuple):
        return list(value[:limit])
    if value in (None, ""):
        return []
    return [value]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _safe_len(value: Any) -> int | None:
    if isinstance(value, (list, tuple, dict, str)):
        return len(value)
    return None


def _unknown_csv_type(index: int) -> dict[str, Any]:
    return {"name": f"unknown_{index}", "unit": "raw", "is_price": False, "with_shipping": False}


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, {}, [])}
