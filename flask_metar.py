# coding=utf-8
from glob import glob
from flask import Flask, render_template, request, session, url_for, redirect, flash
import math
from metar import Metar
import pygeoip
import os
from operator import attrgetter, itemgetter
import heapq
import json
from datetime import datetime, timedelta
from pymongo import MongoClient


app = Flask(__name__)
app.secret_key = '8ks0aCYAOPxdDy6I5KJfh4r9A9IX8YN9'


def metar_str_to_dict(line):
    """
    Parse string with metar data to dictionary with its values.

    Args:
        line: string with metar data

    Returns:
        dictionary with the values
    """
    obs = Metar.Metar(line)

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
        b, c = 17.67, 243.5
        dct['humidity'] = math.exp(
            b * dct['dew_point'] / (c + dct['dew_point']) - b * dct['temperature'] / (c + dct['temperature']))
    else:
        dct['humidity'] = None

    return dct


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
        key=lambda p: math.hypot(p['longitude'] - coords['longitude'], p['latitude'] - coords['latitude']))


def get_airport_data(icao_code):
    """
    Get airport data from airports_data by ICAO code

    Args:
        icao_code: ICAO code of the airport

    Returns:
        airport data for the specified code, if it exists in airports_data
    """
    return [ad for ad in airports_data if ad['icao_code'] == icao_code][0]


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
                'country_en': splitted[2].decode('utf-8'),
                'country_ru': splitted[3].decode('utf-8'),
                'name_en': splitted[4].decode('utf-8'),
                'name_ru': splitted[5].decode('utf-8'),
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
        return None
    return dct


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


def get_data_for(coords):
    """
    Get last metar data for specified coordinates-like object

    Args:
        coords: dict with longitude and latitude items

    Returns:
        dict with items 'airport', 'metar', 'distance' which contain corresponding data
    """
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
        return redirect(url_for('user_page'))
    else:
        return redirect(url_for('city_chooser', next_action='show'))


@app.route('/choose_city/<next_action>')
def city_chooser(next_action):
    """
    City chooser page

    Args:
        next_action: string 'show' to rediret to full city weather page on click,
            or 'add' to add city to the user list
    """
    ip = get_ip()
    ip_obj = get_ip_data(ip)

    if ip_obj.get('city', None) and ip_obj.get('latitude', None) and ip_obj.get('longitude', None):
        nearest_cities = get_nearest_cities(ip_obj, 3)

        for c in nearest_cities:
            c['data'] = get_data_for(c)
    else:
        nearest_cities = None

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
        if any(name.lower().startswith(text.lower()) for name in [c['name_ru'], c['name_en']])
    ]
    cities.sort(key=itemgetter('name_ru'))
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
        flash(u'Ошибка: слишком длинное имя (%s) или пароль (%s)' % (user_name, password), 'error')
        return redirect(url_for('index'))

    if db.users_ids.find({'_id': user_name}).count() == 0:
        db.users_ids.insert({
            '_id': user_name,
            'pwd': password,
            'cities': [],
            'reg_ip': get_ip(),
            'reg_dt': datetime.utcnow(),
        })
        flash(u'Создан новый пользователь: %s' % user_name)
    else:
        user = db.users_ids.find_one({'_id': user_name})
        if user['pwd'] != password:
            flash(u'Ошибка: неверное имя (%s) или пароль (%s)' % (user_name, password), 'error')
            return redirect(url_for('index'))

        flash(u'Вход выполнен: %s' % user_name)

    # set session variable here, because errors are checked
    session['user_name'] = user_name
    return redirect(url_for('user_page'))


@app.route("/logout")
def logout():
    """
    Process user logout, and redirect to index page
    """
    session.clear()
    flash(u'Выход выполнен')
    return redirect(url_for('index'))


@app.route('/user')
def user_page():
    """
    User page, should be opened only when logged in correctly
    """
    user = db.users_ids.find_one({'_id': session['user_name']})
    if not user:
        session.clear()
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


if os.path.isdir('/root/flask-metar/data/'):
    data_folder = '/root/flask-metar/data/'
elif os.path.isdir('/home/alexander/metar/'):
    data_folder = '/home/alexander/metar/'
else:
    raise NotImplemented

cities_data = get_cities_data()
assert all(c['id'] == i for i, c in enumerate(cities_data))

popular_cities_g = [c for c in cities_data if c['name_ru'] in [u'Москва', u'Долгопрудный', u'Сочи']]

airports_data = get_airports_data()
gi_city = pygeoip.GeoIP(data_folder + 'GeoIPCity.dat')

with open(sorted(glob(data_folder + 'observations/*'))[-1]) as f:
    last_data = f.read().splitlines()
    last_data = {line[:4]: line for line in last_data}

app.jinja_env.globals['datetime'] = datetime
app.jinja_env.globals['format_timedelta'] = format_timedelta
app.jinja_env.globals['arrow_class_from_deg'] = arrow_class_from_deg
app.jinja_env.globals['get_distance'] = get_distance

conn = MongoClient()
db = conn.flask_metar


def main():
    app.run(debug=True, host='0.0.0.0')


if __name__ == '__main__':
    main()