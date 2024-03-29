# encoding=utf-8
from glob import glob
from flask import Flask, render_template, request, session, url_for, redirect, flash
from flaskext.babel import Babel, gettext as _, ngettext as _n, refresh as babel_refresh
import math
from metar import Metar
import pygeoip
import os
from operator import attrgetter, itemgetter
import heapq
from datetime import datetime, timedelta
from pymongo import MongoClient
import jinja2_helpers


app = Flask(__name__)
babel = Babel(app)
# doesn't have to be really secret as all app users have equal rights
app.secret_key = '8ks0aCYAOPxdDy6I5KJfh4r9A9IX8YN9'


def metar_str_to_dict(line):
    """
    Parse string with metar data to dictionary with its values.

    Args:
        line: string with metar data

    Returns:
        dictionary with the values
    """
    # parse string using library
    obs = Metar.Metar(line)

    # restructure parsed data
    dct = {
        'station_id': obs.station_id,
        'datetime': obs.time + timedelta(hours=4),
        'temperature': obs.temp.value('C') if obs.temp is not None else None,
        'visibility': (
            obs.vis._gtlt if obs.vis._gtlt else None,
            obs.vis.value('m') if obs.vis is not None else None
        ),
        'wind': {
            'direction': obs.wind_dir.value() if obs.wind_dir is not None else None,
            'speed': obs.wind_speed.value('mps') if obs.wind_speed is not None else None
        },
        'pressure': obs.press.value('mm') if obs.press is not None else None,
        'dew_point': obs.dewpt.value('C') if obs.dewpt is not None else None,
        'clouds': [
            {
                'cover': cover,
                'height': dist.value('m') if dist is not None else None,
                'type': cl_type
            }
            for cover, dist, cl_type in obs.sky
        ] if obs.sky else None,
        'weather': obs.weather if obs.weather else None,
        'trend': obs.trend() if obs.trend() else None,
    }

    if 'dew_point' in dct and 'temperature' in dct:
        # can calculate humidity
        b, c = 17.67, 243.5
        dct['humidity'] = math.exp(
            b * dct['dew_point'] / (c + dct['dew_point']) - b * dct['temperature'] / (c + dct['temperature']))
    else:
        # can't calculate humidity
        dct['humidity'] = None

    return dct


def get_airports_data():
    """
    Read data from airports.txt and return it as a list of dictionaries with values.
    """
    with open(data_folder + 'airports.txt') as f:
        lines = f.read().splitlines()
        objs = [{
                    'icao_code': splitted[1],
                    'name': splitted[2],
                    'latitude': float(splitted[3]),
                    'longitude': float(splitted[4]),
                }
                for l in lines
                for splitted in [l.split('\t')]]
        return objs


def get_nearest_airports(coords, n):
    """
    Get n nearests airports to a coordinates-like object

    Args:
        coords: dict with longitude and latitude items
        n: number of nearest airports to return

    Returns:
        list of dictinaries with data of nearest airports
    """
    return heapq.nsmallest(
        n,
        airports_data,
        # hypot is used instead of get_distance in favour of speed
        key=lambda p: math.hypot(p['longitude'] - coords['longitude'], p['latitude'] - coords['latitude']))


def get_airport_data(icao_code):
    """
    Get airport data from airports_data by ICAO code

    Args:
        icao_code: ICAO code of the airport

    Returns:
        airport data for the specified code, if it exists in airports_data
    """
    return next(ad for ad in airports_data if ad['icao_code'] == icao_code)


def get_cities_data():
    """
    Read data from cities.txt and return it as a list of dictionaries with values.
    """
    with open(data_folder + 'cities.txt') as f:
        lines = f.read().splitlines()
        objs = [
            {
                'id': int(splitted[0]),
                'country_code': splitted[1],
                'country_name': {
                    'en': splitted[2].decode('utf-8'),
                    'ru': splitted[3].decode('utf-8'),
                },
                'name': {
                    'en': splitted[4].decode('utf-8'),
                    'ru': splitted[5].decode('utf-8'),
                },
                'latitude': float(splitted[6]),
                'longitude': float(splitted[7]),
            }
            for l in lines
            for splitted in [l.split('\t')]
        ]
        return objs


def get_nearest_cities(coords, n):
    """
    Get n nearests cities to a coordinates-like object

    Args:
        coords: dict with longitude and latitude items
        n: number of nearest airports to return

    Returns:
        list of dictinaries with data of nearest cities
    """
    return heapq.nsmallest(
        n,
        cities_data,
        # hypot is used instead of get_distance in favour of speed
        key=lambda p: math.hypot(p['longitude'] - coords['longitude'], p['latitude'] - coords['latitude']))


def get_distance(start, end):
    """
    Get distance between two points on the globe

    Args:
        start, end: two points (dicts with longitude and latitude items)

    Returns:
        distance between start and end in kilometers
    """
    start_long = math.radians(start['longitude'])
    start_latt = math.radians(start['latitude'])
    end_long = math.radians(end['longitude'])
    end_latt = math.radians(end['latitude'])
    d_latt = end_latt - start_latt
    d_long = end_long - start_long
    a = math.sin(d_latt / 2) ** 2 + math.cos(start_latt) * math.cos(end_latt) * math.sin(d_long / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return 6371 * c


def get_ip_data(ip):
    """
    Get GeoIP (city) information about an IP address

    Args:
        ip: ip address as a string

    Returns:
        GeoIP information about the IP as a dict
    """
    return gi_city.record_by_addr(ip)


def get_last_data(station_id):
    """
    Get last metar data by a station id (airport ICAO code)

    Args:
        station_id: station id (airport ICAO code)

    Returns:
        dict with last metar data for this station
    """
    try:
        line = last_data[station_id]
        dct = metar_str_to_dict(line)
    except KeyError, Metar.ParserError:
        # no such station, or couldn't parse metar data
        return None
    return dct


def get_data_for(coords):
    """
    Get last metar data for specified coordinates-like object

    Args:
        coords: dict with longitude and latitude items

    Returns:
        dict with items 'airport', 'metar', 'distance' which contain corresponding data
    """
    # get nearest airport for which last metar data exists
    nearest_airports = get_nearest_airports(coords, 10)
    airport = next(a for a in nearest_airports if get_last_data(a['icao_code']))

    return {
        'airport': airport,
        'metar': get_last_data(airport['icao_code']),
        'distance': get_distance(coords, airport)
    }


def get_ip():
    """
    Get the user IP address

    Returns:
        IP address as a string
    """
    if not request.headers.getlist("X-Forwarded-For"):
        ip = request.remote_addr
    else:
        ip = request.headers.getlist("X-Forwarded-For")[0]
    return ip


@app.route('/')
def index():
    """
    Index page: redirect to user page if logged in, and to city chooser otherwise
    """
    if 'user_name' in session:
        # logged in user - redirect to user page
        return redirect(url_for('user_page'))
    else:
        # not logged in - redirect to city chooser page
        return redirect(url_for('city_chooser', next_action='show'))


@app.route('/choose_city/<next_action>')
def city_chooser(next_action):
    """
    City chooser page

    Args:
        next_action: string 'show' to rediret to full city weather page on click,
            or 'add' to add city to the user list
    """
    # IP address and its GeoIP data to show nearest cities
    ip = get_ip()
    ip_obj = get_ip_data(ip)

    if ip_obj.get('city', None) and ip_obj.get('latitude', None) and ip_obj.get('longitude', None):
        # GeoIP location succeded, show nearest cities
        nearest_cities = get_nearest_cities(ip_obj, 3)

        for c in nearest_cities:
            c['data'] = get_data_for(c)
    else:
        # couldn't locate, show no nearest cities
        nearest_cities = None

    # get a copy of global variable
    popular_cities = popular_cities_g[:]

    for c in popular_cities:
        c['data'] = get_data_for(c)

    return render_template(
        'city_chooser.html',
        next_action=next_action,
        nearest_cities=nearest_cities,
        popular_cities=popular_cities)


@app.route('/_search_city/<next_action>')
def search_city(next_action):
    """
    City search results - AJAX response
    Search string should be passed as GET argument named 'text'

    Args:
        next_action: string 'show' to rediret to full city weather page on click,
            or 'add' to add city to the user list
    """
    text = request.args['text']
    cities = [
        c
        for c in cities_data
        # case-independent matching
        if any(name.lower().startswith(text.lower()) for name in [c['name']['ru'], c['name']['en']])
    ]
    locale = get_locale()
    cities.sort(key=lambda c: c['name'][locale])
    # take first 3 search results
    cities = cities[:3]

    for c in cities:
        c['data'] = get_data_for(c)

    return render_template(
        'city_search_results.html',
        next_action=next_action,
        cities=cities)


@app.route('/w/<city_id>/<for_humans>')
def weather(city_id, for_humans):
    """
    Full weather page for a city

    Args:
        city_id: internal city identifier (integer number)
        for_humans: unused argument, contains a string like the city name
    """
    try:
        city_id = int(city_id)
    except ValueError:
        # city_id isn't and integer number
        return redirect(url_for('index'))

    city = cities_data[city_id]
    data = get_data_for(city)

    return render_template(
        'weather.html',
        data=data,
        city=city)


@app.route('/login', methods=['POST'])
def login():
    """
    Process user login: create new user if not exists, or just log in as an existing one
    Username should be supplied as POST argument 'user_name', and password as 'password'
    This immediately redirects to index page (if login is incorrect), or to user page, both with a message
    """
    user_name = request.form['user_name']
    password = request.form['password']

    if len(user_name) + len(password) > 100:
        flash(_(u'Ошибка: слишком длинное имя (%(user)s) или пароль (%(password)s)', user=user_name, password=password),
              'error')
        return redirect(url_for('index'))

    if db.users_ids.find({'_id': user_name}).count() == 0:
        # create new user, also records IP address and creation datetime
        db.users_ids.insert({
            '_id': user_name,
            'pwd': password,
            'cities': [],
            'reg_ip': get_ip(),
            'reg_dt': datetime.utcnow(),
        })
        flash(_(u'Создан новый пользователь: %(user)s', user=user_name))
    else:
        user = db.users_ids.find_one({'_id': user_name})
        if user['pwd'] != password:
            flash(_(u'Ошибка: неверное имя (%(user)s) или пароль (%(password)s)', user=user_name, password=password),
                  'error')
            return redirect(url_for('index'))

        flash(_(u'Вход выполнен: %(user)s', user=user_name))

    # simply set session variable here, because errors are already checked
    session['user_name'] = user_name
    return redirect(url_for('user_page'))


@app.route("/logout")
def logout():
    """
    Process user logout, and redirect to index page
    """
    del session['user_name']
    flash(_(u'Выход выполнен'))
    return redirect(url_for('index'))


@app.route('/user')
def user_page():
    """
    User page, should be opened only when logged in correctly
    """
    if 'user_name' not in session:
        return redirect(url_for('index'))

    user = db.users_ids.find_one({'_id': session['user_name']})
    if not user:
        # username not in database, possibly due to some error
        del session['user_name']
        return redirect(url_for('index'))

    city_ids = user['cities']
    cities = [cities_data[cid] for cid in city_ids]
    for c in cities:
        c['data'] = get_data_for(c)
    return render_template('user_page.html', cities=cities)


@app.route('/add_city/<city_id>/<for_humans>')
def add_city(city_id, for_humans):
    """
    Add a city to the logged in user list, then redirect to user page

    Args:
        city_id: internal city identifier (integer number)
        for_humans: unused argument, contains a string like the city name
    """
    user_name = session['user_name']
    city_id = int(city_id)
    db.users_ids.update({'_id': user_name, 'cities': {'$nin': [city_id]}}, {'$push': {'cities': city_id}})
    return redirect(url_for('user_page'))


@app.route('/remove_city/<city_id>')
def remove_city(city_id):
    """
    Remove a city from the logged in user list, typically called by AJAX

    Args:
        city_id: internal city identifier (integer number)
    """
    user_name = session['user_name']
    city_id = int(city_id)
    db.users_ids.update({'_id': user_name}, {'$pull': {'cities': city_id}})
    return ''


@app.route('/change_language/<language_code>')
def change_language(language_code):
    """
    Set new language to a session variable, or remove it if same as default for this hostname
    After this redirects to referrer page

    Args:
        language_code: language code to be set
    """
    if request.host == 'weather.aplavin.ru':
        default_locale = 'en'
    elif request.host == 'pogoda.aplavin.ru':
        default_locale = 'ru'
    else:
        default_locale = 'en'

    if language_code == default_locale:
        del session['locale']
    else:
        session['locale'] = language_code

    babel_refresh()
    flash(_(u'Язык изменён'))
    return redirect(request.referrer)


@babel.localeselector
def get_locale():
    """
    Select locale which Babel uses for current request
    """
    if 'locale' in session:
        return session['locale']
    elif request.host == 'weather.aplavin.ru':
        return 'en'
    elif request.host == 'pogoda.aplavin.ru':
        return 'ru'
    return 'en'

# determine where it executes: on local PC or remote server
# paths are different there
if os.path.isdir('/root/flask-metar/data/'):
    # remote server
    data_folder = '/root/flask-metar/data/'
elif os.path.isdir('/home/alexander/metar/'):
    # local PC
    data_folder = '/home/alexander/metar/'
else:
    # unknown
    raise NotImplemented

cities_data = get_cities_data()
# simple check to ensure that ids match
assert all(c['id'] == i for i, c in enumerate(cities_data))
# not actually "popular", but "featured"
popular_cities_g = [c for c in cities_data if c['name']['ru'] in [u'Москва', u'Долгопрудный', u'Сочи']]

airports_data = get_airports_data()
gi_city = pygeoip.GeoIP(data_folder + 'GeoIPCity.dat')

# read data from last file in observations directory
with open(sorted(glob(data_folder + 'observations/*'))[-1]) as f:
    last_data = f.read().splitlines()
    # first 4 charactes in line represent ICAO code
    last_data = {line[:4]: line for line in last_data}

# initialize Jinja2 objects used in templates
jinja2_helpers.init(app.jinja_env)
app.jinja_env.globals['get_locale'] = get_locale

# connect to database
conn = MongoClient()
db = conn.flask_metar


def main():
    # if this is run as script, start development server
    # WARN: available from any IP address for convenience
    app.run(debug=True, host='0.0.0.0')


if __name__ == '__main__':
    main()