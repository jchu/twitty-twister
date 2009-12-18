import sys

from twisted.internet import error
from twisted.web import sux, microdom

class NoopParser(object):
    def __init__(self, n):
        self.name = n
        self.done = False
    def gotTagStart(self, name, attrs):
        pass
    def gotTagEnd(self, name, data):
        self.done = (name == self.name)
    def value(self):
        # don't store anything on the object after parsing this
        return None

class BaseXMLHandler(object):

    def __init__(self, n, handler_dict={}, enter_unknown=False):
        self.done = False
        self.current_ob = None
        self.tag_name = n
        self.before_delegates = {}
        self.after_delegates = {}
        self.handler_dict = handler_dict
        self.enter_unknown = enter_unknown

        for p in self.handler_dict:
            self.__dict__[self.cleanup(p)] = None

    def setBeforeDelegate(self, name, fn):
        self.before_delegates[name] = fn

    def setAfterDelegate(self, name, fn):
        self.after_delegates[name] = fn

    def setDelegate(self, name, before=None, after=None):
        if before:
            self.setBeforeDelegate(name, before)
        if after:
            self.setAfterDelegate(name, after)

    def objectStarted(self, name, o):
        if name in self.before_delegates:
            self.before_delegates[name](o)

    def objectFinished(self, name, o):
        if name in self.after_delegates:
            self.after_delegates[name](o)

    def gotTagStart(self, name, attrs):
        if self.current_ob:
            self.current_ob.gotTagStart(name, attrs)
        elif name in self.handler_dict:
            self.current_ob = self.handler_dict[name](name)
            self.objectStarted(name, self.current_ob)
        elif not self.enter_unknown:
            sys.stderr.write("Got unknown tag %s in %s\n" % (name, self.__class__))
            self.current_ob = NoopParser(name)

    def gotTagEnd(self, name, data):
        if self.current_ob:
            self.current_ob.gotTagEnd(name, data)
            if self.current_ob.done:
                v = self.current_ob.value()
                if v is not None:
                    self.__dict__[self.cleanup(name)] = v
                    self.objectFinished(name, v)
                self.current_ob = None
        elif name == self.tag_name:
            self.done = True
            del self.current_ob
            self.gotFinalData(data)

    def gotFinalData(self, data):
        pass

    def value(self):
        # by default, the resulting value is the handler object itself,
        # but XMLStringHandler overwrites this
        return self

    def cleanup(self, n):
        return n.replace(':', '_')

    def __repr__(self):
        return "{%s %s}" % (self.tag_name, self.__dict__)

class XMLStringHandler(BaseXMLHandler):
    """XML data handler for simple string fields"""
    def gotFinalData(self, data):
        self.data = data

    def value(self):
        return self.data


class PredefinedXMLHandler(BaseXMLHandler):
    SIMPLE_PROPS = []
    COMPLEX_PROPS = {}

    # if set to True, contents inside unknown tags
    # will be parsed as if the unknown tags weren't
    # around it.
    ENTER_UNKNOWN = False

    def __init__(self, n):
        handler_dict = dict(simple.COMPLEX_PROPS)
        handler_dict.update([(p,XMLStringHandler) for p in self.SIMPLE_PROPS])
        super(PredefinedXMLHandler, self).__init__(n, handler_dict, self.ENTER_UNKNOWN)

class Author(PredefinedXMLHandler):

    SIMPLE_PROPS = [ 'name', 'uri' ]

class Entry(PredefinedXMLHandler):

    SIMPLE_PROPS = ['id', 'published', 'title', 'content', 'link', 'updated',
                    'twitter:source', 'twitter:lang']
    COMPLEX_PROPS = {'author': Author}

    def gotTagStart(self, name, attrs):
        super(Entry, self).gotTagStart(name, attrs)
        if name == 'link':
            self.__dict__[attrs['rel']] = attrs['href']

    def gotTagEnd(self, name, data):
        super(Entry, self).gotTagEnd(name, data)
        if name == 'link':
            del self.link

class Status(PredefinedXMLHandler):

    SIMPLE_PROPS = ['created_at', 'id', 'text', 'source', 'truncated',
        'in_reply_to_status_id', 'in_reply_to_screen_name',
        'in_reply_to_user_id', 'favorited', 'user_id', 'geo']

class User(PredefinedXMLHandler):

    SIMPLE_PROPS = ['id', 'name', 'screen_name', 'location', 'description',
        'profile_image_url', 'url', 'protected', 'followers_count',
        'profile_background_color', 'profile_text_color', 'profile_link_color',
        'profile_sidebar_fill_color', 'profile_sidebar_border_color',
        'friends_count', 'created_at', 'favourites_count', 'utc_offset',
        'time_zone', 'following', 'notifications', 'statuses_count',
        'profile_background_image_url', 'profile_background_tile', 'verified',
        'geo_enabled']
    COMPLEX_PROPS = {'status': Status}

# Hack to patch this in...

Status.COMPLEX_PROPS = {'user': User}

class SenderUser(User):
    pass

class RecipientUser(User):
    pass

class DirectMessage(PredefinedXMLHandler):

    SIMPLE_PROPS = ['id', 'sender_id', 'text', 'recipient_id', 'created_at',
        'sender_screen_name', 'recipient_screen_name']
    COMPLEX_PROPS = {'sender': SenderUser, 'recipient': RecipientUser}

def topLevelXMLHandler(toplevel_tag, toplevel_type):
    """Used to create a BaseXMLHandler object that just handles a single type of tag"""
    return BaseXMLHandler(None,
                          handler_dict={toplevel_type.MY_TAG:toplevel_type},
                          enter_unknown=True)


class Parser(sux.XMLParser):

    """A file-like thingy that parses a friendfeed feed with SUX."""
    def __init__(self, handler):
        self.connectionMade()
        self.data=[]
        self.handler=handler

    def write(self, b):
        self.dataReceived(b)
    def close(self):
        self.connectionLost(error.ConnectionDone())
    def open(self):
        pass
    def read(self):
        return None

    # XML Callbacks
    def gotTagStart(self, name, attrs):
        self.data=[]
        self.handler.gotTagStart(name, attrs)

    def gotTagEnd(self, name):
        self.handler.gotTagEnd(name, ''.join(self.data).decode('utf8'))

    def gotText(self, data):
        self.data.append(data)

    def gotEntityReference(self, data):
        e = {'quot': '"', 'lt': '&lt;', 'gt': '&gt;', 'amp': '&amp;'}
        if e.has_key(data):
            self.data.append(e[data])
        elif data[0] == '#':
            self.data.append('&' + data + ';')
        else:
            sys.stderr.write("Unhandled entity reference: %s\n" % (data))


def createParser(toplevel_tag, toplevel_type, delegate, extra_args=None):
    if extra_args:
        args = (extra_args,)
    else:
        args = ()

    def do_delegate(e):
        delegate(e, *args)

    handler = topLevelXMLHandler(toplevel_tag, toplevel_type)
    handler.setAfterDelegate(toplevel_tag, do_delegate)
    return Parser(handler)

def simpleParserFactory(toplevel_tag, toplevel_type):
    """Used for simple toplevel_tag/toplevel_type parsers"""
    def create(delegate, extra_args=None):
        """Create a Parser object for the specific tag type, on the fly"""
        return createParser(toplevel_tag, toplevel_type, delegate, extra_args)
    return create





Feed       = simpleParserFactory('entry', Entry)

Users      = simpleParserFactory('user', User)

Direct     = simpleParserFactory('direct_message', DirectMessage)

StatusList = simpleParserFactory('status', Status)

HoseFeed   = simpleParserFactory('status', Status)


def parseXML(xml):
    return microdom.parseXMLString(xml)

def parseUpdateResponse(xml):
    return parseXML(xml).getElementsByTagName("id")[0].firstChild().data

# vim: set expandtab:
