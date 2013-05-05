# encoding=utf-8

jinja_filters = {}


def jinja_filter(arg=None):
    """
    Decorator which adds function to jinja_filters
    """
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
    """
    Format timedelta between t1 and t2 as hours and minutes

    Args:
        t1, t2: two moments in time represented by datetime

    Returns:
        string containing formatted timedelta
    """
    tdelta = t2 - t1
    secs = tdelta.total_seconds()
    mins = int(secs % 3600 / 60)
    hours = int(secs / 3600)
    if hours and mins:
        # both are nonzero
        return u'%s ч %s м' % (hours, mins)
    elif mins:
        # zero hours
        return u'%s м' % mins
    elif hours:
        # zero minutes
        return u'%s ч' % hours


@jinja_filter('arrow_class')
def arrow_class_from_deg(angle):
    """
    Get CSS arrow class which gives the nearest direction to the specified angle

    Args:
        angle: angle in degrees, clockwise, 0 is up arrow

    Returns:
        string containing CSS class name
    """
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