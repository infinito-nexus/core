from utils.domains.unserved import served_domains


class FilterModule:
    def filters(self):
        return {"served_domains": served_domains}
