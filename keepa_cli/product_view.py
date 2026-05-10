"""
keepa_cli/product_view.py
文件说明：把 Keepa Product Object 转换为 Agent 友好的稳定视图。
主要职责：摘要化 csv/history、stats 位置数组、媒体、A+ 与常用商业字段。
依赖边界：不发起 Keepa 请求；调用方负责提供原始响应与 raw output 元数据。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from keepa_cli.keepa_time import keepa_minutes_to_iso


PRODUCT_VIEW_SCHEMA_VERSION = "2026-05-10.1"

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


def build_agent_product_view(data: Mapping[str, Any], *, history_limit: int = 10, media_limit: int = 5) -> dict[str, Any]:
    body = data.get("body")
    products = body.get("products") if isinstance(body, Mapping) else None
    product_items = products if isinstance(products, list) else []
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
        "schema_version": PRODUCT_VIEW_SCHEMA_VERSION,
        "product_count": len(product_items),
        "products": [
            _product_to_agent_view(product, history_limit=max(0, history_limit), media_limit=max(1, media_limit))
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
    return result


def _product_to_agent_view(product: Mapping[str, Any], *, history_limit: int, media_limit: int) -> dict[str, Any]:
    stats = product.get("stats") if isinstance(product.get("stats"), Mapping) else {}
    current = stats.get("current") if isinstance(stats, Mapping) else None
    return {
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
    return _compact(
        {
            "total_offer_count": stats.get("totalOfferCount"),
            "retrieved_offer_count": stats.get("retrievedOfferCount"),
            "offer_count_fba": stats.get("offerCountFBA"),
            "offer_count_fbm": stats.get("offerCountFBM"),
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
                    "30": stats.get("outOfStockPercentage30"),
                    "90": stats.get("outOfStockPercentage90"),
                    "180": stats.get("outOfStockPercentage180"),
                    "365": stats.get("outOfStockPercentage365"),
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
        if raw_value in (-1, None):
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
    if raw_value in (-1, None):
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
    if raw_value in (-1, None):
        return None
    return {"amount": _currency_decimal(raw_value), "raw_value": raw_value, "unit": "currency"}


def _currency_decimal(raw_value: Any) -> float:
    return round(int(raw_value) / 100, 2)


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


def _map_fixed_list(value: Any, keys: list[str]) -> dict[str, Any]:
    if not isinstance(value, list):
        return {}
    return {key: value[index] for index, key in enumerate(keys) if index < len(value)}


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
