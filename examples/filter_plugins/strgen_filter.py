import strgen

def call_strgen(value):
    return strgen.StringGenerator(value).render()

class FilterModule(object):
    '''
    custom jinja2 filter to generate random strings based on a template
    '''

    def filters(self):
        return {
            'strgen': call_strgen
        }
