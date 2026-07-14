from utils.roles.entity_name import get_entity_name


class FilterModule:
    def filters(self):
        return {
            "get_entity_name": get_entity_name,
        }
