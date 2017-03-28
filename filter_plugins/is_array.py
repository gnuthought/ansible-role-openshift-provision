def is_list(value):
    return isinstance(value, list)

class FilterModule(object):
    '''
    custom jinja2 filters for working with collections
    '''

    def filters(self):
        return {
            'is_list': is_list
        }
