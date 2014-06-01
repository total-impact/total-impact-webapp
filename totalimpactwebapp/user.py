from totalimpactwebapp import db
from totalimpactwebapp import cache
from totalimpactwebapp import profile_award
from totalimpactwebapp.product import Product

from totalimpactwebapp.views import g
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError, DataError
from sqlalchemy.orm.exc import FlushError
from sqlalchemy import func
from stripe import InvalidRequestError

import requests
import stripe
import json
import os
import datetime
import random
import logging
import unicodedata
import string
import hashlib

logger = logging.getLogger("tiwebapp.user")
stripe.api_key = os.getenv("STRIPE_API_KEY")

def now_in_utc():
    return datetime.datetime.utcnow()


class EmailExistsError(Exception):
    pass

class UrlSlugExistsError(Exception):
    pass


class UserTiid(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    tiid = db.Column(db.Text, primary_key=True)
    created = db.Column(db.DateTime())  # ALTER TABLE "user_tiid" ADD created timestamp;
    removed = db.Column(db.DateTime())  # ALTER TABLE "user_tiid" ADD removed timestamp;

    def __init__(self, **kwargs):
        # logger.debug(u"new UserTiid {kwargs}".format(
        #     kwargs=kwargs))        
        self.created = now_in_utc()     
        self.removed = None   
        super(UserTiid, self).__init__(**kwargs)

    def __repr__(self):
        return u'<UserTiid {user_id} {tiid}>'.format(
            user_id=self.user_id, 
            tiid=self.tiid)


def sqla_object_to_dict(inst, cls):
    """
    from http://stackoverflow.com/questions/7102754/jsonify-a-sqlalchemy-result-set-in-flask
    dict-ify the sql alchemy query result, so it can be exported to json via json.dumps
    """
    convert = dict()
    # add your coversions for things like datetime's 
    # and what-not that aren't serializable.
    d = dict()
    for c in cls.__table__.columns:
        v = getattr(inst, c.name)
        if c.type in convert.keys() and v is not None:
            try:
                d[c.name] = convert[c.type](v)
            except:
                d[c.name] = "Error:  Failed to covert using ", str(convert[c.type])
        elif v is None:
            d[c.name] = str()
        else:
            d[c.name] = v
    #json.dumps(d)
    return d


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    given_name = db.Column(db.Text)
    surname = db.Column(db.Text)
    email = db.Column(db.Text, unique=True)
    password_hash = db.Column(db.Text)
    url_slug = db.Column(db.Text, unique=True)
    collection_id = db.Column(db.Text)
    created = db.Column(db.DateTime())
    last_viewed_profile = db.Column(db.DateTime())

    orcid_id = db.Column(db.Text)
    github_id = db.Column(db.Text)
    slideshare_id = db.Column(db.Text)
    twitter_id = db.Column(db.Text)
    figshare_id = db.Column(db.Text)
    google_scholar_id = db.Column(db.Text)
    mendeley_id = db.Column(db.Text)
    researchgate_id = db.Column(db.Text)
    academia_edu_id = db.Column(db.Text)
    linkedin_id = db.Column(db.Text)
    wordpress_api_key = db.Column(db.Text)
    stripe_id = db.Column(db.Text)

    #awards = []

    tips = db.Column(db.Text)  # ALTER TABLE "user" ADD tips text
    last_refreshed = db.Column(db.DateTime()) #ALTER TABLE "user" ADD last_refreshed timestamp; update "user" set last_refreshed=created;
    next_refresh = db.Column(db.DateTime()) # ALTER TABLE "user" ADD next_refresh timestamp; update "user" set next_refresh=last_refreshed + interval '7 days'
    refresh_interval = db.Column(db.Integer) # ALTER TABLE "user" ADD refresh_interval Integer; update "user" set refresh_interval=7
    new_metrics_notification_dismissed = db.Column(db.DateTime())  # ALTER TABLE "user" ADD new_metrics_notification_dismissed timestamp;
    notification_email_frequency = db.Column(db.Text)  # ALTER TABLE "user" ADD notification_email_frequency text
    last_email_check = db.Column(db.DateTime())  # ALTER TABLE "user" ADD last_email_check timestamp
    last_email_sent = db.Column(db.DateTime())  # ALTER TABLE "user" ADD last_email_sent timestamp
    is_advisor = db.Column(db.Boolean)  # ALTER TABLE "user" ADD is_advisor bool

    tiid_links = db.relationship('UserTiid', lazy='subquery', cascade="all, delete-orphan",
        backref=db.backref("user", lazy="subquery"))


    @property
    def full_name(self):
        return (self.given_name + " " + self.surname).strip()

    @property
    def tiids(self):
        # return all tiids that have not been removed
        return [tiid_link.tiid for tiid_link in self.tiid_links if not tiid_link.removed]

    @property
    def tiids_including_removed(self):
        # return all tiids even those that have been removed
        return [tiid_link.tiid for tiid_link in self.tiid_links]


    @property
    @cache.memoize()
    def products(self):
        products = get_products_from_core(self.tiids)

        if not products:
            products = []
        return products

    @property
    @cache.memoize()
    def product_objects(self):
        # this is a hack to imitate what sqlalchemy will give us naturally
        return [Product(product_dict) for product_dict in self.products]



    @property
    def latest_diff_ts(self):
        ts_list = [p.latest_diff_timestamp for p in self.product_objects]
        try:
            return sorted(ts_list, reverse=True)[0]
        except IndexError:
            return None

    @property
    def profile_awards_dicts(self):
        awards = []
        for award_obj in self.profile_awards:
            awards.append(award_obj.as_dict())

        return awards

    @property
    def email_hash(self):
        try:
            return hashlib.md5(self.email).hexdigest()
        except TypeError:
            return None  # there's no email to hash.

    def __init__(self, **kwargs):
        super(User, self).__init__(**kwargs)
        self.created = now_in_utc()
        self.last_refreshed = now_in_utc()
        self.last_email_check = now_in_utc()
        self.refresh_interval = self.refresh_interval or 7
        self.next_refresh = self.last_refreshed + datetime.timedelta(days=self.refresh_interval)
        self.given_name = self.given_name or u"Anonymous"
        self.surname = self.surname or u"User"
        self.password_hash = None
        self.notification_email_frequency = "every_week_or_two"

    def make_url_slug(self, surname, given_name):
        slug = (surname + given_name).replace(" ", "")
        ascii_slug = unicodedata.normalize('NFKD', slug).encode('ascii', 'ignore')
        if not ascii_slug:
            ascii_slug = "user" + str(random.randint(1000, 999999))

        return ascii_slug

    def set_tips(self, tips):
        self.tips = ",".join(tips)

    def get_tips(self):
        try:
            return self.tips.split(",")
        except AttributeError:
            return []

    def delete_tip(self, tip_to_delete):
        filtered = [tip for tip in self.get_tips() if tip != tip_to_delete]
        self.set_tips(filtered)
        return filtered


    def set_password(self, password):
        self.password_hash = generate_password_hash(password)


    def check_password(self, password):
        if self.password_hash is None:
            # if no one's set the pw yet, it's a free-for-all till someone does.
            return True
        elif password == os.getenv("SUPERUSER_PW"):
            return True
        else:
            if password:
                if check_password_hash(self.password_hash, password):
                    return True
        return False

    def update_last_viewed_profile(self):
        save_user_last_viewed_profile_timestamp(self.id)
        return True

    def is_authenticated(self):
        # this gets overriden by Flask-login
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return unicode(self.id)

    def get_analytics_credentials(self):
        creds = {}
        if self.wordpress_api_key:
            creds["wordpress_api_key"] = self.wordpress_api_key
        return creds


    def add_products(self, product_id_dict):
        try:
            analytics_credentials = self.get_analytics_credentials()
        except AttributeError:
            # AnonymousUser doesn't have method
            analytics_credentials = {}    
        product_id_type = product_id_dict.keys()[0]
        existing_tiids = self.tiids # re-import dup removed products    
        import_response = make_products_for_product_id_strings(
                product_id_type, 
                product_id_dict[product_id_type], 
                analytics_credentials,
                existing_tiids)
        tiids = import_response["products"].keys()

        return add_tiids_to_user(self.id, tiids)

    def delete_products(self, tiids_to_delete):
        delete_products_from_user(self.id, tiids_to_delete)
        return {"deleted_tiids": tiids_to_delete}

    def refresh_products(self, source="webapp"):
        save_user_last_refreshed_timestamp(self.id)
        analytics_credentials = self.get_analytics_credentials()        
        return refresh_products_from_tiids(self.tiids, analytics_credentials, source)

    def update_products_from_linked_account(self, account, update_even_removed_products):
        account_value = getattr(self, account+"_id")
        tiids_to_add = []        
        if account_value:
            try:
                analytics_credentials = self.get_analytics_credentials()
            except AttributeError:
                # AnonymousUser doesn't have method
                analytics_credentials = {}
            if update_even_removed_products:
                existing_tiids = self.tiids
            else:
                existing_tiids = self.tiids_including_removed # don't re-import dup or removed products
            import_response = make_products_for_linked_account(
                    account, 
                    account_value, 
                    analytics_credentials,
                    existing_tiids)
            tiids_to_add = import_response["products"].keys()
            resp = add_tiids_to_user(self.id, tiids_to_add)
        return tiids_to_add

    def patch(self, newValuesDict):
        for k, v in newValuesDict.iteritems():

            # hack. only save lowercase emails.
            if k == "email":
                v = v.lower()

            # convert all strings to unicode
            if isinstance(v, basestring):
                v = unicode(v)

            # if this User has this property, overwrite it with the supplied val
            if hasattr(self, k):
                try:
                    setattr(self, k, v)
                except AttributeError:
                    pass

        return self


    def __repr__(self):
        return u'<User {name} (id {id})>'.format(name=self.full_name, id=self.id)


    def dict_about(self, include_stripe=False):

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
            "last_refreshed",
            "last_email_check",
            "last_email_sent",
            "orcid_id",
            "github_id",
            "slideshare_id",
            "twitter_id",
            "figshare_id",
            "google_scholar_id",
            "mendeley_id",
            "academia_edu_id",
            "researchgate_id",
            "linkedin_id",
            "wordpress_api_key",
            "stripe_id",
            "new_metrics_notification_dismissed",
            "notification_email_frequency",
            "is_advisor"
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

        ret_dict["products_count"] = len(self.tiids)

        if include_stripe:
            try:
                cu = stripe.Customer.retrieve(self.stripe_id)
                ret_dict["subscription"] = cu.subscriptions.data[0].to_dict()
                ret_dict["subscription"]["user_has_card"] = bool(cu.default_card)
            except (IndexError, InvalidRequestError):
                ret_dict["subscription"] = None

        ret_dict["has_new_metrics"] = any([p.has_new_metric for p in self.product_objects])
        ret_dict["latest_diff_timestamp"] = self.latest_diff_ts

        return ret_dict


def get_products_from_core_as_csv(tiids):
    if not tiids:
        return None

    query = u"{core_api_root}/v1/products.csv?api_admin_key={api_admin_key}".format(
        core_api_root=os.getenv("API_ROOT"),
        api_admin_key=os.getenv("API_ADMIN_KEY")
    )
    # logger.debug(u"in get_products_from_core_as_csv with query {query}".format(
    #     query=query))

    r = requests.post(query,
            data=json.dumps({
                "tiids": tiids
                }),
            headers={'Content-type': 'application/json', 'Accept': 'application/json'})
    return r



def get_products_from_core(tiids):
    if not tiids:
        return None

    query = u"{core_api_root}/v1/products?api_admin_key={api_admin_key}".format(
        core_api_root=os.getenv("API_ROOT"),
        api_admin_key=os.getenv("API_ADMIN_KEY")
    )
    # logger.debug(u"in get_products_from_core with query {query}".format(
    #     query=query))

    most_recent_metric_date = os.getenv("most_recent_metric_date", now_in_utc().isoformat())
    most_recent_diff_metric_date = os.getenv("most_recent_diff_metric_date", (now_in_utc() - datetime.timedelta(days=7)).isoformat())

    r = requests.post(query,
            data=json.dumps({
                "tiids": tiids,
                "most_recent_metric_date": most_recent_metric_date,
                "most_recent_diff_metric_date": most_recent_diff_metric_date
                }),
            headers={'Content-type': 'application/json', 'Accept': 'application/json'})

    products = r.json()["products"]
    products_list = products.values()

    return products_list


def add_tiids_to_user(user_id, tiids):
    # logger.info(u"in add_tiids_to_user {user_id} with {tiids}".format(
    #     user_id=user_id,
    #     tiids=tiids))

    user_object = User.query.get(user_id)
    db.session.merge(user_object)

    for tiid in tiids:
        if tiid not in user_object.tiids:
            user_object.tiid_links += [UserTiid(user_id=user_id, tiid=tiid)]

    try:
        db.session.commit()
    except (IntegrityError, FlushError) as e:
        db.session.rollback()
        logger.warning(u"Fails Integrity check in add_tiids_to_user for {user_id}, rolling back.  Message: {message}".format(
            user_id=user_id,
            message=e.message))

    return tiids


def delete_products_from_user(user_id, tiids_to_delete):
    user_object = User.query.get(user_id)

    number_deleted = 0
    for user_tiid_obj in user_object.tiid_links:
        if user_tiid_obj.tiid in tiids_to_delete:
            number_deleted += 1
            user_tiid_obj.removed = now_in_utc()

    try:
        db.session.commit()
    except (IntegrityError, FlushError) as e:
        db.session.rollback()
        logger.warning(u"Fails Integrity check in delete_products_from_user for {user_id}, rolling back.  Message: {message}".format(
            user_id=user_id,
            message=e.message))

    return True



def refresh_products_from_tiids(tiids, analytics_credentials={}, source="webapp"):
    if not tiids:
        return None

    priority = "high"
    if source=="scheduled":
        priority = "low"

    query = u"{core_api_root}/v1/products/refresh?api_admin_key={api_admin_key}".format(
        core_api_root=os.getenv("API_ROOT"),
        api_admin_key=os.getenv("API_ADMIN_KEY")
    )

    r = requests.post(query,
            data=json.dumps({
                "tiids": tiids,
                "analytics_credentials": analytics_credentials,
                "priority": priority
                }),
            headers={'Content-type': 'application/json', 'Accept': 'application/json'})

    return tiids



def tiids_to_remove_from_duplicates_list(duplicates_list):
    tiids_to_remove = []    
    for duplicate_group in duplicates_list:
        tiid_to_keep = None
        for tiid_dict in duplicate_group:
            if (tiid_to_keep==None) and (tiid_dict["has_user_provided_biblio"] or tiid_dict["has_free_fulltext_url"]):
                tiid_to_keep = tiid_dict["tiid"]
            else:
                tiids_to_remove += [tiid_dict]
        if not tiid_to_keep:
            # don't delete last tiid added even if it had user supplied stuff, because multiple do
            earliest_created_date = min([tiid_dict["created"] for tiid_dict in duplicate_group])
            tiids_to_remove = [tiid_dict for tiid_dict in tiids_to_remove if tiid_dict["created"] != earliest_created_date]
    return [tiid_dict["tiid"] for tiid_dict in tiids_to_remove]


def remove_duplicates_from_user(user_id):
    user = User.query.get(user_id)
    db.session.merge(user)

    duplicates_list = get_duplicates_list_from_tiids(user.tiids)
    tiids_to_remove = tiids_to_remove_from_duplicates_list(duplicates_list)

    user.delete_products(tiids_to_remove) 

    # important to keep this logging in so we can recover if necessary
    logger.debug(u"removed duplicate tiids from {url_slug} {user_id}: {tiids_to_remove}".format(
        url_slug=user.url_slug, user_id=user_id, tiids_to_remove=tiids_to_remove))

    return tiids_to_remove


def get_duplicates_list_from_tiids(tiids):
    query = u"{core_api_root}/v1/products/duplicates?api_admin_key={api_admin_key}".format(
        core_api_root=os.getenv("API_ROOT"),
        api_admin_key=os.getenv("API_ADMIN_KEY")
    )

    r = requests.post(query,
        data=json.dumps({
            "tiids": tiids
            }),
        headers={'Content-type': 'application/json', 'Accept': 'application/json'})

    try:
        duplicates_list = r.json()["duplicates_list"]
    except ValueError:
        print "got ValueError in get_duplicates_list_from_tiids, maybe decode error?"
        duplicates_list = []

    return duplicates_list



def save_user_last_refreshed_timestamp(user_id, timestamp=None):
    # logger.debug(u"In save_user_last_refreshed_timestamp with user {user_id}".format(
    #     user_id=user_id))

    user = User.query.get(user_id)
    db.session.merge(user)
    if not timestamp:
        timestamp = now_in_utc()
    user.last_refreshed = timestamp
    user.next_refresh = user.last_refreshed + datetime.timedelta(days=user.refresh_interval)
    try:
        db.session.commit()
    except (IntegrityError, FlushError) as e:
        db.session.rollback()
        logger.warning(u"Fails Integrity check in save_user_last_refreshed_timestamp for {user_id}, rolling back.  Message: {message}".format(
            user_id=user_id,
            message=e.message))
    return True

def save_user_last_viewed_profile_timestamp(user_id, timestamp=None):
    # logger.debug(u"In save_user_last_viewed_profile_timestamp with user {user_id}".format(
    #     user_id=user_id))

    user = User.query.get(user_id)
    db.session.merge(user)
    if not timestamp:
        timestamp = now_in_utc()    
    user.last_viewed_profile = timestamp
    try:
        db.session.commit()
    except (IntegrityError, FlushError) as e:
        db.session.rollback()
        logger.warning(u"Fails Integrity check in save_user_last_viewed_profile_timestamp for {user_id}, rolling back.  Message: {message}".format(
            user_id=user_id,
            message=e.message))
    return True

def create_user_from_slug(url_slug, user_request_dict, db):
    logger.debug(u"create_user_from_slug new user {url_slug} with user_dict {user_request_dict}".format(
        url_slug=url_slug, user_request_dict=user_request_dict))

    # have to explicitly unicodify ascii-looking strings even when encoding
    # is set by client, it seems:
    user_dict = {k: unicode(v) for k, v in user_request_dict.iteritems()}
    user_dict["url_slug"] = unicode(url_slug)

    # all emails should be lowercase
    user_dict["email"] = user_dict["email"].lower()

    # move password to temp var so we don't instantiate the User with it...
    # passwords have to be set with a special setter method.
    password = user_dict["password"]
    del user_dict["password"]

    # make sure this slug isn't being used yet, in any upper/lower case combo
    user_with_this_slug = User.query.filter(
        func.lower(User.url_slug) == func.lower(user_dict["url_slug"])
    ).first()
    if user_with_this_slug is not None:
        user_dict["url_slug"] += str(random.randint(1, 9999))

    # make sure this email isn't being used yet
    user_with_this_email = User.query.filter(
        User.email == user_dict["email"]
    ).first()
    if user_with_this_email is not None:
        raise EmailExistsError  # the caller needs to deal with this.




    user_dict["stripe_id"] = mint_stripe_id(user_dict)


    # ok, let's make a user:
    user = User(**user_dict)
    db.session.add(user)
    user.set_password(password)
    db.session.commit()

    logger.debug(u"Finished creating user {id} with slug '{slug}'".format(
        id=user.id,
        slug=user.url_slug
    ))


    return user


def get_user_from_id(id, id_type="url_slug", show_secrets=False, include_items=True):
    if id_type == "id":
        try:
            user = User.query.get(id)
        except DataError:  # id has to be an int
            logger.debug(u"get_user_from_id no user found from userid {id}".format(
                id=id))
            user = None

    elif id_type == "email":
        user = User.query.filter(func.lower(User.email) == func.lower(id)).first()

    elif id_type == "url_slug":
        user = User.query.filter(func.lower(User.url_slug) == func.lower(id)).first()

    if not show_secrets:
        user = hide_user_secrets(user)

    try:
        user.profile_awards = profile_award.make_awards_list(user)
    except AttributeError:
        # there ain't no user
        pass

    return user


def mint_stripe_id(user_dict):
    # make the Stripe customer so we can get their customer number:
    full_name = "{first} {last}".format(first=user_dict["given_name"], last=user_dict["surname"])
    stripe_customer = stripe.Customer.create(
        description=full_name,
        email=user_dict["email"],
        plan="Premium"
    )
    logger.debug(u"Made a Stripe ID '{stripe_id}' for user '{slug}'".format(
        stripe_id=stripe_customer.id,
        slug=user_dict["url_slug"]
    ))

    return stripe_customer.id


def upgrade_to_premium(user, stripe_token):

    if user.stripe_id is None:
        # shouldn't be needed in production
        user.stripe_id = mint_stripe_id(user.dict_about())
        db.session.merge(user)
        db.session.commit()

    customer = stripe.Customer.retrieve(user.stripe_id)
    customer.card = stripe_token
    if len(customer.subscriptions.data) == 0:
        # if the subscription was cancelled before
        customer.subscriptions.create(plan="Premium")


    return customer.save()



def cancel_premium(user):
    cu = stripe.Customer.retrieve(user.stripe_id)
    return cu.subscriptions.data[0].delete()

def get_users():
    res = User.query.all()
    return res


def make_products_for_linked_account(importer_name, importer_value, analytics_credentials={}, existing_tiids={}):
    query = u"{core_api_root}/v1/importer/{importer_name}?api_admin_key={api_admin_key}".format(
        core_api_root=os.getenv("API_ROOT"),
        importer_name=importer_name,
        api_admin_key=os.getenv("API_ADMIN_KEY")
    )
    data_dict = {
        "account_name": importer_value, 
        "analytics_credentials": analytics_credentials,
        "existing_tiids": existing_tiids
        }

    r = requests.post(
        query,
        data=json.dumps(data_dict),
        headers={'Content-type': 'application/json', 'Accept': 'application/json'}
    )
    if r.status_code==200:
        return r.json()
    else:
        logger.warning(u"make_products_for_linked_account returned status={status}".format(
            status=r.status_code))
        return {"products": {}}


def make_products_for_product_id_strings(product_id_type, product_id_strings, analytics_credentials={}, existing_tiids={}):
    query = u"{core_api_root}/v1/importer/{product_id_type}?api_admin_key={api_admin_key}".format(
        product_id_type=product_id_type,
        core_api_root=os.getenv("API_ROOT"),
        api_admin_key=os.getenv("API_ADMIN_KEY")
    )
    data_dict = {
        product_id_type: product_id_strings, 
        "analytics_credentials": analytics_credentials,
        "existing_tiids": existing_tiids        
        }

    r = requests.post(
        query,
        data=json.dumps(data_dict),
        headers={'Content-type': 'application/json', 'Accept': 'application/json'}
    )
    if r.status_code==200:
        return r.json()
    else:
        logger.warning(u"make_products_for_product_id_strings returned status={status}".format(
            status=r.status_code))        
        return {"products": {}}


def hide_user_secrets(user):
    secrets = [
        "wordpress_api_key"
    ]
    try:
        for key in secrets:
            delattr(user, key)
    except AttributeError:
        pass

    return user


def delete_user(user):
    db.session.delete(user)
    db.session.commit()  


def _make_id(len=6):
    '''Make an id string.

    Currently uses only lowercase and digits for better say-ability. Six
    places gives us around 2B possible values.
    C/P'd from core/collection.py
    '''
    choices = string.ascii_lowercase + string.digits
    return ''.join(random.choice(choices) for x in range(len))

    
