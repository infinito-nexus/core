from utils.roles.entity.name import entity_name


class FilterModule:
    def filters(self):
        return {
            "entity_name": entity_name,
        }
