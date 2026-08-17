def band_score(value, bands):
    """Return the score for the first band whose minimum is met."""
    for minimum, score in bands:
        if value >= minimum:
            return score
    return 0


class ScoreNormalizer:
    @staticmethod
    def normalize(value, minimum, maximum):
        if maximum == minimum:
            return 0.0
        result = (value - minimum) / (maximum - minimum) * 100
        return max(0.0, min(100.0, result))
