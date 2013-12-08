import re

def add_category_heading_products(products):

    categories = categorize_products(products)



    heading_products_list = []

    for category_key, category_products in categories.iteritems():

        heading_product = make_heading_product_for_category(
            category_key[0],  # genre
            category_key[1],  # account
            category_products
        )

        heading_products_list.append(heading_product)

    return heading_products_list + remove_account_products(products)


def make_heading_product_for_category(genre, account, category_products):

    anchor = genre
    if account:
        anchor += "-" + re.sub(r"[^\w]", r"-", account)

    anchor = anchor.replace("--", "-")

    heading_product = {
        'isHeading': True,
        '_id': anchor,
        'genre': genre,
        'account': account,
        'headingDimension': 'category',
        'summary':{
            'numProducts': len(category_products)
        }
    }

    for product in category_products:
        if "is_account" in product["biblio"].keys():
            heading_product["metrics"] = product["metrics"]

    return heading_product


def remove_account_products(products):
    ret = []
    for product in products:

        try:
            if not product['biblio']['is_account']:
                ret.append(product)
        except KeyError:
            ret.append(product)

    return ret


def categorize_products(products):
    categories = {}
    for product in products:
        genre = product["biblio"]["genre"]
        try:
            account = product["biblio"]["account"].lower()
        except KeyError:
            account = None


        categories.setdefault((genre, account), []).append(product)

    return categories


def add_sort_keys(products):
    for product in products:
        try:
            product["genre"] = product["biblio"]["genre"]
        except KeyError:
            product["genre"] = "unknown"

        try:
            product["account"] = product["biblio"]["account"]
        except KeyError:
            product["account"] = None

    return products