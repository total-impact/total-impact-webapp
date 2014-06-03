from totalimpactwebapp.card import Card
from totalimpactwebapp.util import as_int_or_float_if_possible
from totalimpactwebapp import configs

import requests
import os
import json
import datetime
import arrow


def products_above_threshold(products, metric_name, threshold):
    above_threshold = []
    for product in products:
        for metric in product.metrics:
            if metric.metric_name == metric_name:
                if metric.display_count >= threshold:
                    above_threshold.append(product)
    return above_threshold


def get_percentile(metric):
    top_percentile = metric.top_percentile
    if top_percentile:
        return 100 - top_percentile
    else:
        return None


def get_threshold_just_crossed(current_value, diff_value, thresholds):

    try:
        previous_value = current_value - diff_value
    except TypeError:
        # not numeric
        return None

    for threshold in sorted(thresholds, reverse=True):
        if (current_value >= threshold) and (previous_value < threshold):
            return threshold
    return None

def get_median(metric, medians_lookup, year, genre):
    try:
        median = medians_lookup[genre][metric.percentiles["refset"]][year][metric.metric_name]
    except (KeyError, TypeError):
        median = None
    return median


def populate_card(user_id, tiid, metric, metric_name, thresholds_lookup=[], medians_lookup={}, timestamp=None):
    hist = metric.historical_values
    current_value = as_int_or_float_if_possible(hist["current"]["raw"])
    diff_value = as_int_or_float_if_possible(hist["diff"]["raw"])
    thresholds = thresholds_lookup.get(metric_name, [])
    newest_diff_timestamp = arrow.get(hist["current"]["collected_date"]).datetime
    oldest_diff_timestamp = arrow.get(hist["previous"]["collected_date"]).datetime

    my_card = Card(
        card_type="new metrics",
        granularity="product",
        metric_name=metric_name,
        user_id=user_id,
        tiid=tiid,
        diff_value=diff_value,
        current_value=current_value,
        newest_diff_timestamp=newest_diff_timestamp,
        oldest_diff_timestamp=oldest_diff_timestamp, 
        diff_window_days = (newest_diff_timestamp - oldest_diff_timestamp).days,
        percentile_current_value=get_percentile(metric),
        threshold_awarded=get_threshold_just_crossed(current_value, diff_value, thresholds),
        weight=0.7,
        timestamp=timestamp
    )

    return my_card



def get_medians_lookup():
    api_root = os.getenv("API_ROOT", "http://total-impact-core.herokuapp.com")
    url = api_root + "/collections/reference-sets-medians"
    resp = requests.get(url)
    return json.loads(resp.text)


class CardGenerator:
    pass











"""
 ProductNewMetricCardGenerator
 *************************************************************************** """


class ProductNewMetricCardGenerator(CardGenerator):

    @classmethod
    def make(cls, user, products, timestamp=None):
        thresholds_lookup = configs.metrics(this_key_only="milestones")

        medians_lookup = get_medians_lookup()
        if not timestamp:
            timestamp = datetime.datetime.utcnow()

        cards = []

        for product in products:
            for metric in product.metrics:
                diff_value = metric.historical_values["diff"]["raw"]

                # this card generator only makes cards with weekly diffs
                if diff_value:
                    new_card = populate_card(user.id, product.tiid, metric, metric.metric_name, thresholds_lookup, medians_lookup, timestamp)

                    # now populate with profile-level information
                    peers = products_above_threshold(products, metric.metric_name, new_card.current_value)
                    new_card.num_profile_products_this_good = len(peers)
                    new_card.median = get_median(metric, medians_lookup, product.biblio.year, product.genre)

                    # and keep the card
                    cards.append(new_card)

        return cards




"""
 ProfileNewMetricCardGenerator
 *************************************************************************** """


class ProfileNewMetricCardGenerator(CardGenerator):

    @classmethod
    def make(cls, user, products, timestamp=None):
        thresholds_lookup = configs.metrics(this_key_only="milestones")


        medians_lookup = get_medians_lookup()
        if not timestamp:
            timestamp = datetime.datetime.utcnow()

        metrics_to_accumulate = []
        cards = []
        metric_totals = {}

        for (metric_name, thresholds) in thresholds_lookup.iteritems():

            if "citations" in metric_name:
                continue  # we aren't allowed to accumulate scopus, don't want to accumulate PMC ciations

            accumulating_card = Card(
                    card_type="new metrics",
                    granularity="profile",
                    metric_name=metric_name,
                    user_id=user.id,
                    newest_diff_timestamp=arrow.get(datetime.datetime.min).datetime,  #initiate with a very recent value
                    oldest_diff_timestamp=arrow.get(datetime.datetime.max).datetime,  #initiate with a very recent value
                    diff_value=0,
                    current_value=0,
                    weight=0.8, 
                    timestamp=timestamp
                )            

            for product in products:
                metric = product.metric_by_name(metric_name)
                if metric:
                    hist = metric.historical_values
                    product_current_value = as_int_or_float_if_possible(hist["current"]["raw"])
                    product_diff_value = as_int_or_float_if_possible(hist["diff"]["raw"])
                    current_diff_timestamp = arrow.get(hist["current"]["collected_date"]).datetime
                    previous_diff_timestamp = arrow.get(hist["previous"]["collected_date"]).datetime

                    try:
                        accumulating_card.current_value += product_current_value
                        accumulating_card.diff_value += product_diff_value
                    except (TypeError, AttributeError):
                        pass
                    if current_diff_timestamp > accumulating_card.newest_diff_timestamp:
                        accumulating_card.newest_diff_timestamp = current_diff_timestamp
                    if previous_diff_timestamp < accumulating_card.oldest_diff_timestamp:
                        accumulating_card.oldest_diff_timestamp = previous_diff_timestamp


            # only keep card if accumulating
            if accumulating_card.diff_value:
                accumulating_card.threshold_awarded = get_threshold_just_crossed(
                    accumulating_card.current_value, 
                    accumulating_card.diff_value, 
                    thresholds)
                if accumulating_card.threshold_awarded:
                    accumulating_card.diff_window_days = (accumulating_card.newest_diff_timestamp - accumulating_card.oldest_diff_timestamp).days
                    cards.append(accumulating_card)

        return cards












