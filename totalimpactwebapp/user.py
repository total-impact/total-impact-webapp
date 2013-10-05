from totalimpactwebapp import db
from totalimpactwebapp.views import g
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import DataError

import requests
import json
import os
import datetime
import random
import logging
import unicodedata
import string
import hashlib

logger = logging.getLogger("tiwebapp.user")

def now_in_utc():
    return datetime.datetime.utcnow()



class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    given_name = db.Column(db.String(64))
    surname = db.Column(db.String(64))
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(120))
    url_slug = db.Column(db.String(100), unique=True)
    collection_id = db.Column(db.String(12))
    created = db.Column(db.DateTime())
    last_viewed_profile = db.Column(db.DateTime())

    orcid_id = db.Column(db.String(64))
    github_id = db.Column(db.String(64))
    slideshare_id = db.Column(db.String(64))

    @property
    def full_name(self):
        return (self.given_name + " " + self.surname).strip()

    @property
    def email_hash(self):
        try:
            return hashlib.md5(self.email).hexdigest()
        except TypeError:
            return None  # there's no email to hash.

    def __init__(self, **kwargs):
        super(User, self).__init__(**kwargs)
        self.created = now_in_utc()
        self.given_name = self.given_name or u"Anonymous"
        self.surname = self.surname or u"User"

    def make_url_slug(self, surname, given_name):
        slug = (surname + given_name).replace(" ", "")
        ascii_slug = unicodedata.normalize('NFKD', slug).encode('ascii', 'ignore')
        if not ascii_slug:
            ascii_slug = "user" + str(random.randint(1000, 999999))

        return ascii_slug


    def uniqueify_slug(self):
        self.url_slug += str(random.randint(1000, 99999))
        return self.url_slug


    def set_last_viewed_profile(self):
        self.last_viewed_profile = now_in_utc()


    def set_password(self, password):
        self.password_hash = generate_password_hash(password)


    def check_password(self, password):

        if self.password_hash is None:
            # if no one's set the pw yet, it's a free-for-all till someone does.
            return True
        elif check_password_hash(self.password_hash, password):
            return True
        elif password == os.getenv("SUPERUSER_PW"):
            return True
        else:
            return False


    def is_authenticated(self):
        # this gets overriden by Flask-login
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return unicode(self.id)

    def get_products(self, get_products=1):
        return get_collection_from_core(
            self.collection_id,
            get_products
        )

    def patch(self, newValuesDict):
        for k, v in newValuesDict.iteritems():
            if hasattr(self, k):
                try:
                    setattr(self, k, v)
                except AttributeError:
                    pass

        return self


    def add_products(self, tiids_to_add):
        return add_products_to_core_collection(
            self.collection_id, tiids_to_add)["items"]

    def delete_products(self, tiids_to_delete):
        return delete_products_from_core_collection(self.collection_id, tiids_to_delete)

    def refresh_products(self):
        return refresh_products_from_core_collection(self.collection_id)



    def __repr__(self):
        return '<User {name}>'.format(name=self.full_name)


    def as_dict(self):

        properties_to_return = [
            "id",
            "given_name",
            "surname",
            "email",
            "email_hash",
            "url_slug",
            "collection_id",
            "created",
            "last_viewed_profile",
            "orcid_id",
            "github_id",
            "slideshare_id"
        ]

        ret_dict = {}
        for property in properties_to_return:
            val = getattr(self, property, None)
            try:
                # if we want dict, we probably want something json-serializable
                val = val.isoformat()
            except AttributeError:
                pass

            ret_dict[property] = val

        return ret_dict




def get_collection_from_core(collection_id, include_items=1):
    logger.debug(u"running a GET query for /collection/{collection_id} the api".format(
        collection_id=collection_id))

    query = u"{core_api_root}/v1/collection/{collection_id}?api_admin_key={api_admin_key}".format(
        core_api_root=g.roots["api"],
        api_admin_key=os.getenv("API_ADMIN_KEY"),
        collection_id=collection_id
    )
    r = requests.get(query, params={"include_items": include_items})

    return r.json()


def get_products_from_core(collection_id):
    coll_obj = get_collection_from_core(collection_id)
    return coll_obj["items"]



def add_products_to_core_collection(collection_id, tiids_to_add):
    query = "{core_api_root}/v1/collection/{collection_id}/items?api_admin_key={api_admin_key}".format(
        core_api_root=g.roots["api"],
        api_admin_key=os.getenv("API_ADMIN_KEY"),
        collection_id=collection_id
    )

    print "sending this query: ", query
    print "sending these tiids: ", tiids_to_add

    r = requests.put(query,
            data=json.dumps({"tiids": tiids_to_add}),
            headers={'Content-type': 'application/json', 'Accept': 'application/json'})

    return r.json()


def delete_products_from_core_collection(collection_id, tiids_to_delete):
    query = "{core_api_root}/v1/collection/{collection_id}/items?api_admin_key={api_admin_key}".format(
        core_api_root=g.roots["api"],
        api_admin_key=os.getenv("API_ADMIN_KEY"),
        collection_id=collection_id
    )
    r = requests.post(query, 
            params={"http_method": "DELETE"}, 
            data=json.dumps({"tiids": tiids_to_delete}), 
            headers={'Content-type': 'application/json', 'Accept': 'application/json'})

    return r.json()


def refresh_products_from_core_collection(collection_id):
    query = "{core_api_root}/v1/collection/{collection_id}?api_admin_key={api_admin_key}".format(
        core_api_root=g.roots["api"],
        api_admin_key=os.getenv("API_ADMIN_KEY"),
        collection_id=collection_id
    )
    r = requests.post(
        query,
        headers={'Content-type': 'application/json', 'Accept': 'application/json'}
    )

    return r.json()


def make_collection_for_user(user, alias_tiids, prepped_request):
    email = user.email.lower()

    prepped_request.headers = {'Content-type': 'application/json', 'Accept': 'application/json'}
    prepped_request.data = {"aliases": alias_tiids, "title": email}
    r = requests.Session.send(prepped_request)

    user.collection_id = r.json()["collection"]["_id"]
    return user





def create_user_from_slug(url_slug, user_request_dict, api_root, db):
    logger.debug(u"Creating new user")

    unicode_request_dict = {k: unicode(v) for k, v in user_request_dict.iteritems()}
    unicode_request_dict["url_slug"] = unicode(url_slug)

    # create the user's collection first
    # ----------------------------------
    url = api_root + "/v1/collection?api_admin_key={api_admin_key}".format(
        api_admin_key=os.getenv("API_ADMIN_KEY"))
    data = {
        "title": unicode_request_dict["url_slug"]
    }

    try:
        data["tiids"] = unicode_request_dict["tiids"]
    except KeyError:
        data["tiids"] = []

    headers = {'Content-type': 'application/json', 'Accept': 'application/json'}

    r = requests.post(url, data=json.dumps(data), headers=headers)
    print "we got this back when we made teh collection: ", r.json()
    unicode_request_dict["collection_id"] = r.json()["collection"]["_id"]


    # then create the actual user
    #----------------------------

    # have to explicitly unicodify ascii-looking strings even when encoding
    # is set by client, it seems:
    user = User(**unicode_request_dict)

    db.session.add(user)
    db.session.commit()

    logger.debug(u"Finished creating user {id} with slug '{slug}'".format(
        id=user.id,
        slug=user.url_slug
    ))

    return user


def get_user_from_id(id, id_type="userid", include_items=True):
    if id_type == "userid":
        try:
            user = User.query.get(id)
        except DataError:  # id has to be an int
            user = None

    elif id_type == "email":
        user = User.query.filter_by(email=id).first()

    elif id_type == "url_slug":
        user = User.query.filter_by(url_slug=id).first()

    if include_items:
        try:
            user.products = get_products_from_core(user.collection_id)
        except AttributeError:  # user has no collection_id  'cause it's None
            pass

    return user


def make_genre_heading_products(products):
    genre_names = set([product["biblio"]["genre"] for product in products])


    print("genre names:", genre_names)

    genre_heading_products = []
    for genre_name in genre_names:
        heading_product = {
            "isHeading": True,
            "headingDimension": "genre",
            "headingValue": genre_name
        }
        genre_heading_products.append(heading_product)


    print("genre_heading_products", genre_heading_products)

    return genre_heading_products





def _make_id(len=6):
    '''Make an id string.

    Currently uses only lowercase and digits for better say-ability. Six
    places gives us around 2B possible values.
    C/P'd from core/collection.py
    '''
    choices = string.ascii_lowercase + string.digits
    return ''.join(random.choice(choices) for x in range(len))