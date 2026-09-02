class TargetManager:

    def next_target(self, position):
        """Return the next configured target based on the current LTP."""
        targets = [
            getattr(position, "target1", 0.0),
            getattr(position, "target2", 0.0),
            getattr(position, "target3", 0.0),
        ]
        targets = [target for target in targets if target and target > 0]

        if not targets:
            return None

        for target in targets:
            if position.ltp < target:
                return target

        return targets[-1]
