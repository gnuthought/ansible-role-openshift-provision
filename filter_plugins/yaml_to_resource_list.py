import yaml
import re

def yaml_to_resource_list(value):
    resource_list = []
    for yaml_doc in value.split("\n---\n"):
        resource = yaml.load(yaml_doc)
        if resource:
            if resource.get('kind', '') == 'List':
                resource_list.extend(resource.get('items',[]))
            else:
                resource_list.append(resource)
    return resource_list

class FilterModule(object):
    '''
    custom jinja2 filters for handling yaml documents with resource definitions
    '''

    def filters(self):
        return {
            'yaml_to_resource_list': yaml_to_resource_list
        }
