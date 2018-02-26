"""
 play_video.py
 refactored based on Jukebox Activity
 Copyright (C) 2007 Andy Wingo <wingo@pobox.com>
 Copyright (C) 2007 Red Hat, Inc.
 Copyright (C) 2008-2010 Kushal Das <kushal@fedoraproject.org>
 Copyright (C) 2010-2011 Walter Bender
"""

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307
# USA


import logging
import os

import gi
gi.require_version('Gtk','3.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk
from gi.repository import GObject
from gi.repository import Gst
from gi.repository import Gdk
GObject.threads_init()
import urllib


def play_movie_from_file(parent, filepath, x, y, w, h):
    """ Video media """
    if parent.vplay is not None and parent.vplay.player is not None:
        if parent.vplay.player.playing:
            parent.vplay.player.stop()
        if parent.vplay.bin is not None:
            parent.vplay.bin.destroy()

    parent.vplay = Vplay(x, y, w, h)
    parent.vplay.start(filepath)


def stop_media(parent):
    """ Called from Clean block and toolbar Stop button """
    if parent.vplay == None:
        return

    if parent.vplay.player is not None:
        parent.vplay.player.stop()
    if parent.vplay.bin != None:
        parent.vplay.bin.destroy()

    parent.vplay = None


def media_playing(parent):
    if parent.vplay == None:
        return False
    return parent.vplay.player.is_playing()


class Vplay():
    UPDATE_INTERVAL = 500

    def __init__(self, x=0, y=0, w=0, h=0):

        self.player = None
        self.uri = None
        self.playlist = []
        self.jobjectlist = []
        self.playpath = None
        self.got_stream_info = False
        self.currentplaying = 0

        self.bin = Gtk.Window()

        self.videowidget = VideoWidget()
        self.bin.add(self.videowidget)
        self.bin.set_type_hint(Gdk.WindowTypeHint.NORMAL)
        self.bin.set_decorated(False)

        self.bin.move(int(x), int(y))
        self.bin.resize(int(w), int(h))
        self.bin.show_all()

        self._want_document = True

    def _player_eos_cb(self, widget):
        logging.debug('end of stream')

    def _player_error_cb(self, widget, message, detail):
        self.player.stop()
        self.player.set_uri(None)
        logging.debug('Error: %s - %s' % (message, detail))

    def _player_stream_info_cb(self, widget, stream_info):
        if not len(stream_info) or self.got_stream_info:
            return

        GST_STREAM_TYPE_VIDEO = 2
        self.got_stream_info = True

    def start(self, uri=None):
        self._want_document = False
        self.playpath = os.path.dirname(uri)
        if not uri:
            return False
        self.playlist.append('file://' + urllib.quote(os.path.abspath(uri)))
        if not self.player:
            # lazy init the player so that videowidget is realized
            # and has a valid widget allocation
            self.player = GstPlayer(self.videowidget)
            self.player.connect('eos', self._player_eos_cb)
            self.player.connect('error', self._player_error_cb)
            self.player.connect('stream-info', self._player_stream_info_cb)

        try:
            if not self.currentplaying:
                logging.info('Playing: ' + self.playlist[0])
                self.player.set_uri(self.playlist[0])
                self.currentplaying = 0
                self.play_toggled()
                self.show_all()
            else:
                pass
        except:
            pass
        return False

    def play_toggled(self):
        if self.player.is_playing():
            self.player.pause()
        else:
            if self.player.error:
                pass
            else:
                self.player.play()


class GstPlayer(GObject.GObject):
    __gsignals__ = {
        'error': (GObject.SIGNAL_RUN_FIRST, None, [str, str]),
        'eos': (GObject.SIGNAL_RUN_FIRST, None, []),
        'stream-info': (GObject.SIGNAL_RUN_FIRST, None, [object])}

    def __init__(self, videowidget):
        GObject.GObject.__init__(self)

        self.playing = False
        self.error = False

        self.player = Gst.ElementFactory.make('playbin', 'player')

        self.videowidget = videowidget
        self._init_video_sink()

        bus = self.player.get_bus()
        bus.enable_sync_message_emission()
        bus.add_signal_watch()
        bus.connect('sync-message::element', self.on_sync_message)
        bus.connect('message', self.on_message)

    def set_uri(self, uri):
        self.player.set_property('uri', uri)

    def on_sync_message(self, bus, message):
        if message.structure is None:
            return
        if message.structure.get_name() == 'prepare-xwindow-id':
            self.videowidget.set_sink(message.src)
            message.src.set_property('force-aspect-ratio', True)

    def on_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logging.debug('Error: %s - %s' % (err, debug))
            self.error = True
            self.emit('eos')
            self.playing = False
            self.emit('error', str(err), str(debug))
        elif t == Gst.MessageType.EOS:
            self.emit('eos')
            self.playing = False
        elif t == Gst.MessageType.STATE_CHANGED:
            old, new, pen = message.parse_state_changed()
            if old == Gst.State.READY and new == Gst.State.PAUSED:
                self.emit('stream-info',
                          self.player.props.stream_info_value_array)

    def _init_video_sink(self):
        self.bin = Gst.Bin()
        videoscale = Gst.ElementFactory.make('videoscale')
        self.bin.add(videoscale)
        pad = videoscale.get_pad('sink')
        ghostpad = Gst.GhostPad('sink', pad)
        self.bin.add_pad(ghostpad)
        videoscale.set_property('method', 0)

        caps_string = 'video/x-raw-yuv, '
        r = self.videowidget.get_allocation()
        if r.width > 500 and r.height > 500:
            # Sigh... xvimagesink on the XOs will scale the video to fit
            # but ximagesink in Xephyr does not.  So we live with unscaled
            # video in Xephyr so that the XO can work right.
            w = 480
            h = float(w) / float(float(r.width) / float(r.height))
            caps_string += 'width=%d, height=%d' % (w, h)
        else:
            caps_string += 'width=480, height=360'

        caps = Gst.Caps.from_string(caps_string)
        self.filter = Gst.ElementFactory.make('capsfilter', 'filter')
        self.bin.add(self.filter)
        self.filter.set_property('caps', caps)

        conv = Gst.ElementFactory.make('ffmpegcolorspace', 'conv')
        self.bin.add(conv)
        videosink = Gst.ElementFactory.make('autovideosink')
        self.bin.add(videosink)
        videoscale.link(self.filter)
        self.filter.link(conv)
        conv.link(videosink)
        self.player.set_property('video-sink', self.bin)

    def pause(self):
        self.player.set_state(Gst.State.PAUSED)
        self.playing = False
        logging.debug('pausing player')

    def play(self):
        self.player.set_state(Gst.State.PLAYING)
        self.playing = True
        self.error = False
        logging.debug('playing player')

    def stop(self):
        self.player.set_state(Gst.State.NULL)
        self.playing = False
        logging.debug('stopped player')

    def get_state(self, timeout=1):
        return self.player.get_state(timeout=timeout)

    def is_playing(self):
        return self.playing


class VideoWidget(Gtk.DrawingArea):

    def __init__(self):
        Gtk.DrawingArea.__init__(self)
        self.set_events(Gdk.EventMask.EXPOSURE_MASK)
        self.imagesink = None
        self.set_double_buffered(False)
        self.set_app_paintable(True)

    def do_expose_event(self, event):
        if self.imagesink:
            self.imagesink.expose()
            return False
        else:
            return True

    def set_sink(self, sink):
        assert self.get_property("window").xid
        self.imagesink = sink
        self.imagesink.set_xwindow_id(self.get_property("window").xid)
