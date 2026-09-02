class TargetManager:

    def next_target(self, position):
        """Return the next target that has not yet been reached."""
        if position.ltp >= position.target3:
            return position.target3
        if position.ltp >= position.target2:
            return position.target3
        if position.ltp >= position.target1:
            return position.target2
        return position.target1
