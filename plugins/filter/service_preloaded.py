from utils.roles.applications.services.preload import preloaded


class FilterModule:
    def filters(self):
        return {"service_preloaded": preloaded}
