# encoding=utf-8

jinja_filters = {}


def jinja_filter(arg=None):
    def decorate(func):
        jinja_filters[name or func.__name__] = func
        return func

    if callable(arg):
        name = arg.__name__
        return decorate(arg)
    else:
        name = arg
        return decorate


@jinja_filter
def format_timedelta(t1, t2):
    tdelta = t2 - t1
    secs = tdelta.total_seconds()
    mins = int(secs % 3600 / 60)
    hours = int(secs / 3600)
    if hours and mins:
        return u'%s ч %s м' % (hours, mins)
    elif mins:
        return u'%s м' % mins
    elif hours:
        return u'%s ч' % hours


@jinja_filter('arrow_class')
def arrow_class_from_deg(angle):
    if angle is None:
        return ''
    arrow_directions = [
        (0, 'n'),
        (45, 'ne'),
        (90, 'e'),
        (135, 'se'),
        (180, 's'),
        (225, 'sw'),
        (270, 'w'),
        (315, 'nw'),
        (360, 'n')
    ]
    return min(arrow_directions, key=lambda (ang, _): abs(ang - angle))[1]


def init(jinja_env):
    jinja_env.filters.update(jinja_filters)