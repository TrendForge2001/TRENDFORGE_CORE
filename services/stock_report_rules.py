"""Readable descriptions of current executed policies; no strategy mutations."""


def readable_rules(definition, horizon):
    result = {
        k: definition[k]
        for k in (
            "strategy_id",
            "name",
            "entry_rules",
            "exit_rules",
            "target_rules",
            "stoploss_rules",
        )
    }
    key = definition["strategy_id"]
    yearly_vwma = key == "tf_daily_vwma20_50_rsi_fibonacci_yearly"
    weekly = key == "tf_weekly_gap_recovery_ema50_100_floor"
    if weekly:
        return result
    result["exit_rules"] = [
        "Bearish setups close existing long positions; they do not open shorts."
    ]
    if horizon == "long_term" or yearly_vwma:
        result["target_rules"] = [
            (
                "Book 50% at yearly R1; manage the remaining "
                "position toward yearly R2/R3 under the appro"
                "ved continuation and trailing conditions."
            )
        ]
        result["stoploss_rules"] = [
            (
                "Either complete rule group exits: (A) RSI14 "
                "below 30 and an opening gap below the previo"
                "us candle close; or (B) a bearish candle wit"
                "h volume above SMA20 and a close below the s"
                "econd yearly pivot below the actual buying p"
                "rice."
            ),
            "A breach of the support reference alone does not trigger an exit.",
        ]
    elif key == "tf_swing_ema20_50_rsi_volume":
        result["target_rules"] = [
            (
                "Use the approved EMA20 profit trail; there i"
                "s no fixed numeric take-profit target."
            )
        ]
        result["stoploss_rules"] = [
            (
                "Exit after two completed daily candles close"
                " below their respective EMA50 values, using "
                "post-entry candles."
            )
        ]
    elif key == "tf_swing_vwma9_26_rsi_volume":
        result["target_rules"] = [
            (
                "A daily close below VWMA9 is an exit only wi"
                "th RSI14 below 50 and volume above SMA20."
            )
        ]
        result["stoploss_rules"] = [
            (
                "A daily close below VWMA26 is an exit only w"
                "ith RSI14 below 50 and volume above SMA20."
            )
        ]
    elif key == "tf_ema20_50_bullish_pivot":
        result["target_rules"] = [
            (
                "Use the next qualifying pivot or previous sw"
                "ing high under the approved pivot plan."
            )
        ]
        result["stoploss_rules"] = [
            "Exit on a completed close below EMA50 or the entry's pivot support."
        ]
    if "vwma" in key:
        result["exit_rules"].append(
            "VWMA exits retain RSI14 and above-average Vo"
            "lume SMA20 confirmation; a VWMA-line cross a"
            "lone is insufficient."
        )
    return result
