# This script takes Amazon "Order History Reports" and annotates your Mint
# transactions based on actual items in each purchase. It can handle orders
# that are split into multiple shipments/charges, and can even itemized each
# transaction for maximal control over categorization.

# First, you must generate and download your order history reports from:
# https://www.amazon.com/gp/b2b/reports

from collections import defaultdict, namedtuple, Counter
# import datetime
# import itertools
import logging
# import readchar
# import time

from mintamazontagger import amazon
from mintamazontagger.my_progress import no_progress_factory

from mintamazontagger.orderhistory import fetch_order_history

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

UpdatesResult = namedtuple(
    'UpdatesResult',
    field_names=(
        'success',
        'items', 'orders', 'refunds', 'stats'))
    # defaults=(
        # False,
        # None, None, None, None))


def create_updates(
        args,
        bq_client,
        on_critical,
        indeterminate_progress_factory=no_progress_factory,
        determinate_progress_factory=no_progress_factory,
        counter_progress_factory=no_progress_factory):
    items_csv = args.items_csv
    orders_csv = args.orders_csv
    refunds_csv = args.refunds_csv

    start_date = None

    if not items_csv or not orders_csv:
        start_date = args.order_history_start_date
        end_date = args.order_history_end_date
        if not args.amazon_email or not args.amazon_password:
            on_critical(
                'Amazon email or password is empty. Please try again')
            return UpdatesResult()

        items_csv, orders_csv, refunds_csv = fetch_order_history(
            args.report_download_location, start_date, end_date,
            args.amazon_email, args.amazon_password,
            args.session_path, args.headless,
            progress_factory=indeterminate_progress_factory)

    if not items_csv or not orders_csv:  # Refunds are optional
        on_critical(
            'Order history either not provided at or unable to fetch. '
            'Exiting.')
        return UpdatesResult()

    try:
        orders = amazon.Order.parse_from_csv(
            orders_csv,
            progress_factory=determinate_progress_factory)
        items = amazon.Item.parse_from_csv(
            items_csv,
            progress_factory=determinate_progress_factory)
        refunds = ([] if not refunds_csv
                   else amazon.Refund.parse_from_csv(
                       refunds_csv,
                       progress_factory=determinate_progress_factory))

    except AttributeError as e:
        msg = (
            'Error while parsing Amazon Order history report CSV files: '
            '{}'.format(e))
        logger.exception(msg)
        on_critical(msg)
        return UpdatesResult()

    if not len(orders):
        on_critical(
            'The Orders report contains no data. Try '
            'downloading again. Report used: {}'.format(
                orders_csv))
        return UpdatesResult()
    if not len(items):
        on_critical(
            'The Items report contains no data. Try '
            'downloading again. Report used: {}'.format(
                items_csv))
        return UpdatesResult()

    # Initialize the stats. Explicitly initialize stats that might not be
    # accumulated (conditionals).
    stats = Counter(
        adjust_itemized_tax=0,
        already_up_to_date=0,
        misc_charge=0,
        new_tag=0,
        no_retag=0,
        retag=0,
        user_skipped_retag=0,
        personal_cat=0,
    )

    return UpdatesResult(
        True, items, orders, refunds, stats)


def print_dry_run(orig_trans_to_tagged, ignore_category=False):
    for orig_trans, new_trans in orig_trans_to_tagged:
        oid = orig_trans.orders[0].order_id
        print('\nFor Amazon {}: {}\nInvoice URL: {}'.format(
            'Order' if orig_trans.is_debit else 'Refund',
            oid, amazon.get_invoice_url(oid)))

        if orig_trans.children:
            for i, trans in enumerate(orig_trans.children):
                print('{}{}) Current: \t{}'.format(
                    '\n' if i == 0 else '',
                    i + 1,
                    trans.dry_run_str()))
        else:
            print('\nCurrent: \t{}'.format(
                orig_trans.dry_run_str()))

        if len(new_trans) == 1:
            trans = new_trans[0]
            print('\nProposed: \t{}'.format(
                trans.dry_run_str(ignore_category)))
        else:
            for i, trans in enumerate(reversed(new_trans)):
                print('{}{}) Proposed: \t{}'.format(
                    '\n' if i == 0 else '',
                    i + 1,
                    trans.dry_run_str(ignore_category)))
