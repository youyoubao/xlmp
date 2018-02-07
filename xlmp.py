﻿#!/usr/bin/python3
# -*- coding:utf-8 -*-
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import logging

from threading import Thread, Event
from urllib.parse import quote, unquote
from time import sleep, time

from bottle import abort, post, redirect, request, route, run, static_file, template, default_app

os.chdir(os.path.dirname(os.path.abspath(__file__)))  # set file path as current
sys.path = ['lib'] + sys.path  # added libpath
from dlnap import URN_AVTransport_Fmt, discover  # https://github.com/ttopholm/dlnap

app = default_app()

VIDEO_PATH = './media'  # media file path
HISTORY_DB_FILE = '%s/.history.db' % VIDEO_PATH  # history db file

# initialize logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(filename)s %(levelname)s [line:%(lineno)d] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')


class DMRTracker(Thread):
    """DLNA Digital Media Renderer tracker thread"""

    def __init__(self, *args, **kwargs):
        super(DMRTracker, self).__init__(*args, **kwargs)
        self._flag = Event()
        self._flag.set()
        self._running = Event()
        self._running.set()
        self.state = {}  # DMR device state
        self.dmr = None  # DMR device object
        self.all_devices = []  # DMR device list
        self._failure = 0
        self._load = None
        logging.info('DMR Tracker initialized.')

    def discover_dmr(self):
        logging.debug('Starting DMR search...')
        if self.dmr:
            logging.info('Current DMR: %s' % self.dmr)
        self.all_devices = discover(name='', ip='', timeout=3, st=URN_AVTransport_Fmt, ssdp_version=1)
        if len(self.all_devices) > 0:
            self.dmr = self.all_devices[0]
            logging.info('Found DMR device: %s' % self.dmr)

    def set_dmr(self, str_dmr):
        for i in self.all_devices:
            if str(i) == str_dmr:
                self.dmr = i
                return True
        return False

    def get_transport_state(self):
        info = self.dmr.info()
        if info:
            self.state['CurrentTransportState'] = info['CurrentTransportState']
            return info['CurrentTransportState']
        else:
            self._failure += 1
            logging.warning('Losing DMR when get transport state. count: %d' % self._failure)
        # try:
            # info = self.dmr.info()
            # if info:
                # self.state['CurrentTransportState'] = info['CurrentTransportState']
                # return info['CurrentTransportState']
            # else:
                # self._failure += 1
                # logging.warning('Losing DMR count when get transport state: %d' % self._failure)
        # except Exception as e:
            # logging.info(e)

    def run(self):
        while self._running.isSet():
            self._flag.wait()
            if self.dmr:
                self.state['CurrentDMR'] = str(self.dmr)
                self.state['DMRs'] = [str(i) for i in self.all_devices]
                sleep(0.1)
                self.get_transport_state()
                sleep(0.1)
                try:
                    position_info = self.dmr.position_info()
                    for i in ('RelTime', 'TrackDuration'):
                        self.state[i] = position_info[i]
                    if self.state['CurrentTransportState'] == 'PLAYING':
                        if position_info['TrackURI']:
                        
                            self.state['TrackURI'] = unquote(re.sub('http://.*/video/', '', position_info['TrackURI']))
                            save_history(self.state['TrackURI'], time_to_second(self.state['RelTime']),
                                         time_to_second(self.state['TrackDuration']))
                        else:
                            logging.info('no Track uri')
                    if self._failure > 0:
                        logging.info('reset failure count from %d to 0' % self._failure)
                        self._failure = 0
                except TypeError:
                    
                    self._failure += 1
                    logging.warning('Losing DMR count: %d' % self._failure, exc_info=True)
                    if self._failure >= 3:
                        # self._failure = 0
                        logging.info('No DMR currently.')
                        self.state = {}
                        self.dmr = None
                except Exception as e:
                    logging.warning('DMR Tracker Exception: %s' % e)
                sleep(1)
            else:
                self.discover_dmr()
                sleep(2.6)

    def pause(self):
        self._flag.clear()

    def resume(self):
        self._flag.set()

    def stop(self):
        self._flag.set()
        self._running.clear()

    def loadonce(self, url):
        try:
            while self.get_transport_state() not in ('STOPPED', 'NO_MEDIA_PRESENT'):
                self.dmr.stop()
                logging.info('Waiting for DMR stopped...')
                sleep(0.85)
            if self.dmr.set_current_media(url):
                logging.info('Loaded %s' % url)
            else:
                logging.warning('Load url failed: %s' % url)
                return False
            time0 = time()
            while self.get_transport_state() not in ('PLAYING', 'TRANSITIONING'):
                self.dmr.play()
                logging.info('Waiting for DMR playing...')
                sleep(0.3)
                if (time() - time0) > 5:
                    logging.info('waiting for DMR playing timeout')
                    return False
            sleep(0.5)
            time0 = time()
            logging.info('checking duration to make sure loaded...')
            while self.dmr.position_info()['TrackDuration'] == '00:00:00':
                sleep(0.5)
                logging.info('Waiting for duration correctly recognized, url=%s' % url)
                if (time() - time0) > 9:
                    logging.info('Load duration timeout')
                    return False
            logging.info(self.state)
        except Exception as e:
            # logging.warning('DLNA load exception: %s\n%s' % (e, traceback.format_exc()))
            logging.warning('DLNA load exception: %s' % e, exc_info=True)
            return False
        return True

    # def loader(self, url):
        # if self._load and self._load.isAlive():
            # logging.info('stopping previous load')
            # self._load.stop()
        # self._load = DLNALoad(url)
        # logging.info('Start new loader, thread name: %s' % self._load.name)
        # self._load.start()
        # return 'Start loading...'


# class DLNALoad(Thread):
    # """Load url through DLNA thread"""

    # def __init__(self, url, *args, **kwargs):
        # super(DLNALoad, self).__init__(*args, **kwargs)
        # # self._running = Event()
        # # self._running.set()
        # self._to_stop = Event()
        # self._failure = 0
        # self._url = url
        # logging.info('DLNA URL load initialized.')

    # def run(self):
        # loadable.wait()
        # loadable.clear()
        # logging.info('started: clear loadable')
        # tracker.pause()
        # # while self._running.isSet() and self._failure < 3:
        # while self._failure < 3:
            # # if not self._running.isSet():
            # if self._to_stop.isSet():
                # logging.info('end because of another request. url: %s' % self._url)
                # logging.info('set loadable')
                # loadable.set()
                # return
            # if tracker.loadonce(self._url):
                # logging.info('Loaded url: %s successed' % self._url)
                # src = unquote(re.sub('http://.*/video/', '', self._url))
                # position = load_history(src)
                # if position:
                    # tracker.dmr.seek(second_to_time(position))
                    # logging.info('Loaded position: %s' % second_to_time(position))
                # logging.info('set loadable')
                # loadable.set()
                # tracker.resume()
                # logging.info('tracker resume')
                # logging.info('Load Successed.')
                # tracker.state['CurrentTransportState'] = 'Load Successed.'
                # return
                # # return 'Load Successed.'
            # self._failure += 1
            # logging.info('Load failed for %s time(s)' % self._failure)
            # tracker.state['CurrentTransportState'] = 'Load Failed %d.' % self._failure
            # sleep(1)
        # logging.info('set loadable')
        # loadable.set()
        # logging.warning('Load aborted. url: %s' % self._url)
        # tracker.resume()
        # logging.info('tracker resume')
        # tracker.state['CurrentTransportState'] = 'Error: Load aborted'
        # return 'Error: Load aborted'

    # def stop(self):
        # # self._running.clear()
        # self._to_stop.set()
        # # logging.info('DLNA load STOP received, waiting for stop.')

        
class DLNALoader(Thread):
    """Load url through DLNA"""

    def __init__(self, *args, **kwargs):
        super(DLNALoader, self).__init__(*args, **kwargs)
        self._running = Event()
        self._running.set()
        self._flag = Event()
        self._failure = 0
        self._url = ''
        logging.info('DLNA URL loader initialized.')

    def run(self):
        while self._running.isSet():
            self._flag.wait()
            tracker.pause()
            url = self._url
            if tracker.loadonce(url):
                logging.info('Loaded url: %s successed' % url)
                src = unquote(re.sub('http://.*/video/', '', url))
                position = load_history(src)
                if position:
                    tracker.dmr.seek(second_to_time(position))
                    logging.info('Loaded position: %s' % second_to_time(position))
                logging.info('Load Successed.')
                tracker.state['CurrentTransportState'] = 'Load Successed.'
                if url == self._url:
                    self._flag.clear()
            else:
                self._failure += 1
                if self._failure >= 3:
                    self._flag.clear()
            tracker.resume()
            logging.info('tracker resume')

    def stop(self):
        self._running.clear()

    def load(self, url):
        self._url = url
        self._failure = 0
        self._flag.set()

# loadable = Event()
# loadable.set()

tracker = DMRTracker()
tracker.start()

loader = DLNALoader()
loader.start()


def check_dmr_exist(func):
    def no_dmr(*args, **kwargs):
        if not tracker.dmr:
            return 'Error: No DMR.'
        return func(*args, **kwargs)
    return no_dmr


def run_sql(sql, *args):
    with sqlite3.connect(HISTORY_DB_FILE) as conn:
        try:
            cursor = conn.execute(sql, args)
            ret = cursor.fetchall()
            cursor.close()
            if cursor.rowcount > 0:
                conn.commit()
        except Exception as e:
            logging.warning(str(e))
            ret = ()
    return ret


def second_to_time(second):
    """ Turn time in seconds into "hh:mm:ss" format

    second: int value
    """
    m, s = divmod(second, 60)
    h, m = divmod(second/60, 60)
    return '%02d:%02d:%06.3f' % (h, m, s)


def time_to_second(time_str):
    """ Turn time in "hh:mm:ss" format into seconds

    time_str: string like "hh:mm:ss"
    """
    return sum([float(i)*60**n for n, i in enumerate(str(time_str).split(':')[::-1])])


def get_size(*filename):
    size = os.path.getsize('%s/%s' % (VIDEO_PATH, ''.join(filename)))
    if size < 0:
        return 'Out of Range'
    elif size < 1024:
        return '%dB' % size
    else:
        unit = ' KMGTPEZYB'
        l = min(int(math.floor(math.log(size, 1024))), 9)
        return '%.1f%sB' % (size/1024.0**l, unit[l])


def load_history(name):
    position = run_sql('select POSITION from history where FILENAME=?', name)
    if len(position) == 0:
        return 0
    return position[0][0]


def save_history(src, position, duration):
    if float(position) < 10:
        return
    run_sql('''replace into history (FILENAME, POSITION, DURATION, LATEST_DATE)
               values(? , ?, ?, DateTime('now', 'localtime'));''', src, position, duration)


@route('/list')
def list_history():
    """Return play history list"""
    return json.dumps([{'filename': s[0], 'position': s[1], 'duration': s[2],
                        'latest_date': s[3], 'path': os.path.dirname(s[0])}
                       for s in run_sql('select * from history order by LATEST_DATE desc')])


@route('/')
def index():
    if tracker.dmr:
        redirect('/dlna')
    return template('index.tpl')


@route('/index')
def index_o():
    return template('index.tpl')


@route('/dlna')
def dlna():
    return template('dlna_player.tpl')


@route('/play/<src:re:.*\.((?i)mp)4$>')
def play(src):
    """Video play page"""
    if not os.path.exists('%s/%s' % (VIDEO_PATH, src)):
        redirect('/')
    return template('player.tpl', src=src, title=src, position=load_history(src))


@route('/setdmr/<dmr>')
def set_dlna_dmr(dmr):
    if tracker.set_dmr(dmr):
        return 'Success'
    else:
        return 'Failed'


@route('/searchdmr')
def search_dmr():
    tracker.discover_dmr()


def get_next_file(src):
    fullname = '%s/%s' % (VIDEO_PATH, src)
    filepath = os.path.dirname(fullname)
    dirs = os.listdir(filepath)
    dirs = [i for i in dirs if os.path.isfile('%s/%s' % (filepath, i))]
    dirs.sort()
    next_index = dirs.index(os.path.basename(fullname)) + 1
    if next_index > len(dirs):
        return None
    else:
        t = '%s/%s' % (filepath, dirs[next_index])
        t = t.replace(VIDEO_PATH, '')
        return t.lstrip('/')


@route('/dlnaload/<src:re:.*\.((?i)(mp4|mkv|avi|flv|rmvb|wmv))$>')
@check_dmr_exist
def dlna_load(src):
    if not os.path.exists('%s/%s' % (VIDEO_PATH, src)):
        logging.warning('File not found: %s' % src)
        return 'Error: File not found.'
    # logging.info('start loading... tracker state:%s' % tracker.state['CurrentTransportState'])
    logging.info('start loading... tracker state:%s' % tracker.state)
    url = 'http://%s/video/%s' % (request.urlparts.netloc, quote(src))
    loader.load(url)
    return 'loading %s' % src
    # return tracker.loader(url)


def result(r):
    if r:
        return 'Done.'
    else:
        return 'Error: Failed!'


@route('/dlnaplay')
@check_dmr_exist
def dlna_play():
    try:
        return result(tracker.dmr.play())
    except Exception as e:
        return 'Play failed: %s' % e


@route('/dlnanext')
@check_dmr_exist
def dlna_next():
    next_file = get_next_file(tracker.state['TrackURI'])
    logging.info('set next file: %s' % next_file)
    if next_file:
        dlna_load(next_file)
    else:
        return 'To the end'


@route('/dlnapause')
@check_dmr_exist
def dlna_pause():
    """Pause video through DLNA"""
    return result(tracker.dmr.pause())


@route('/dlnastop')
@check_dmr_exist
def dlna_stop():
    """Stop video through DLNA"""
    return result(tracker.dmr.stop())


@route('/dlnainfo')
def dlna_info():
    """Get play info through DLNA"""
    return tracker.state


@route('/dlnavol/<control:re:(up|down)>')
@check_dmr_exist
def dlna_volume_control(control):
    """Tune volume through DLNA"""
    vol = int(tracker.dmr.get_volume())
    if control == 'up':
        vol += 1
    elif control == 'down':
        vol -= 1
    if vol < 0 or vol > 100:
        return 'volume range exceeded'
    elif tracker.dmr.volume(vol):
        return str(vol)
    else:
        return 'failed'


@route('/dlnaseek/<position>')
@check_dmr_exist
def dlna_seek(position):
    """Seek video through DLNA"""
    if ':' in position:
        return result(tracker.dmr.seek(position))
    else:
        return result(tracker.dmr.seek(second_to_time(float(position))))


@route('/clear')
def clear():
    """Clear play history list"""
    run_sql('delete from history')
    return list_history()


@route('/remove/<src:path>')
def remove(src):
    """Remove from play history list"""
    run_sql('delete from history where FILENAME=?', unquote(src))
    return list_history()


@route('/move/<src:path>')
def move(src):
    """Move file to '.old' folder"""
    filename = '%s/%s' % (VIDEO_PATH, src)
    dir_old = '%s/%s/.old' % (VIDEO_PATH, os.path.dirname(src))
    if not os.path.exists(dir_old):
        os.mkdir(dir_old)
    try:
        shutil.move(filename, dir_old)  # gonna do something when file is occupied
    except Exception as e:
        logging.warning('move file failed: %s' % e)
        abort(404, str(e))
    return fs_dir('%s/' % os.path.dirname(src))


@post('/save/<src:path>')
def save(src):
    """Save play position"""
    position = request.forms.get('position')
    duration = request.forms.get('duration')
    save_history(src, position, duration)


@route('/deploy')
def deploy():
    """deploy"""
    if sys.platform == 'linux':
        return os.system('/usr/local/bin/deploy')


# @post('/suspend')
# def suspend():
    # """Suepend server"""
    # if sys.platform == 'win32':
        # import ctypes
        # dll = ctypes.WinDLL('powrprof.dll')
        # if dll.SetSuspendState(0, 1, 0):
            # return 'Suspending...'
        # else:
            # return 'Suspend Failure!'
    # else:
        # return 'OS not supported!'


# @post('/shutdown')
# def shutdown():
    # """Shutdown server"""
    # if sys.platform == 'win32':
        # os.system("shutdown.exe -f -s -t 0")
    # else:
        # os.system("sudo /sbin/shutdown -h now")
    # return 'shutting down...'


@route('/backup')
def backup():
    """backup history"""
    return shutil.copyfile(HISTORY_DB_FILE, '%s.bak' % HISTORY_DB_FILE)


@route('/restore')
def restore():
    """restore history"""
    return shutil.copyfile('%s.bak' % HISTORY_DB_FILE, HISTORY_DB_FILE)


@route('/static/<filename:path>')
def static(filename):
    """Static file access"""
    return static_file(filename, root='./static')


@route('/video/<src:re:.*\.((?i)(mp4|mkv|avi|flv|rmvb|wmv))$>')
def static_video(src):
    """video file access
       To support large file(>2GB), you should use web server to deal with static files.
       For example, you can use 'AliasMatch' or 'Alias' in Apache
    """
    return static_file(src, root=VIDEO_PATH)


@route('/fs/<path:re:.*>')
def fs_dir(path):
    """Get static folder list in json"""
    if path == '/':
        path = ''
    try:
        up, list_folder, list_mp4, list_video, list_other = [], [], [], [], []
        if path:
            # up = [{'filename': '..', 'type': 'folder', 'path': '/%s..' % path}]  # path should be path/
            up = [{'filename': '..', 'type': 'folder', 'path': '%s..' % path}]  # path should be path/
            if not path.endswith('/'):
                path = '%s/' % path
        dir_list = os.listdir('%s/%s' % (VIDEO_PATH, path))  # path could be either path or path/
        dir_list.sort()
        for filename in dir_list:
            if filename.startswith('.'):
                continue
            if os.path.isdir('%s/%s%s' % (VIDEO_PATH, path, filename)):
                list_folder.append({'filename': filename, 'type': 'folder',
                                    'path': '%s%s' % (path, filename)})
            elif re.match('.*\.((?i)mp)4$', filename):
                list_mp4.append({'filename': filename, 'type': 'mp4',
                                'path': '%s%s' % (path, filename), 'size': get_size(path, filename)})
            elif re.match('.*\.((?i)(mkv|avi|flv|rmvb|wmv))$', filename):
                list_video.append({'filename': filename, 'type': 'video',
                                   'path': '%s%s' % (path, filename), 'size': get_size(path, filename)})
            else:
                list_other.append({'filename': filename, 'type': 'other',
                                  'path': '%s%s' % (path, filename), 'size': get_size(path, filename)})
        return json.dumps(up + list_folder + list_mp4 + list_video + list_other)
    except Exception as e:
        logging.warning('dir exception: %s' % e)
        abort(404, str(e))

# Initialize DataBase
run_sql('''create table if not exists history
                (FILENAME text PRIMARY KEY not null,
                POSITION float not null,
                DURATION float, LATEST_DATE datetime not null);''')


if __name__ == '__main__':  # for debug
    from imp import find_module
    if sys.platform == 'win32':
        os.system('start http://127.0.0.1:8081/')  # open the page automatic for debug
    try:
        find_module('meinheld')
        run(host='0.0.0.0', port=8081, debug=True, server='meinheld')  # run demo server use meinheld
    except Exception:
        run(host='0.0.0.0', port=8081, debug=True)  # run demo server
