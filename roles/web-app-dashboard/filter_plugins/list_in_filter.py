class FilterModule:
    """Custom filters for Ansible"""

    def filters(self):
        return {
            "any_in": self.any_in,
        }

    def any_in(self, list1, list2):
        """
        Checks if at least one element from list1 is found in list2.

        :param list1: List of elements to check.
        :param list2: Target list in which to search for elements.
        :return: True if at least one element is found, otherwise False.
        """
        # If either parameter is not a list, return False.
        if not isinstance(list1, list) or not isinstance(list2, list):
            return False

        # Iterate over list1 and check if an element exists in list2.
        return any(element in list2 for element in list1)
