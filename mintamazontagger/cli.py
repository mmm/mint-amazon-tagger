#!/usr/bin/env python3

# This script fetches Amazon "Order History Reports" and annotates your Mint
# transactions based on actual items in each purchase. It can handle orders
# that are split into multiple shipments/charges, and can even itemized each
# transaction for maximal control over categorization.

import argparse
from collections import defaultdict
import logging
import os
import time

from outdated import check_outdated

from mintamazontagger import amazon
from mintamazontagger import mint
from mintamazontagger import bq_importer
from mintamazontagger import VERSION
from mintamazontagger.args import define_cli_args, TAGGER_BASE_PATH
from mintamazontagger.my_progress import (
    counter_progress_cli, determinate_progress_cli, indeterminate_progress_cli)
from mintamazontagger.currency import micro_usd_to_usd_string
from mintamazontagger.bqclient import BigQueryClient

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def main():
    root_logger = logging.getLogger()
    root_logger.addHandler(logging.StreamHandler())
    # For helping remote debugging, also log to file.
    # Developers should be vigilant to NOT log any PII, ever (including being
    # mindful of what exceptions might be thrown).
    log_directory = os.path.join(TAGGER_BASE_PATH, 'Tagger Logs')
    os.makedirs(log_directory, exist_ok=True)
    log_filename = os.path.join(log_directory, '{}.log'.format(
        time.strftime("%Y-%m-%d_%H-%M-%S")))
    root_logger.addHandler(logging.FileHandler(log_filename))

    is_outdated, latest_version = check_outdated('mint-amazon-tagger', VERSION)
    if is_outdated:
        print('Please update your version by running:\n'
              'pip3 install mint-amazon-tagger --upgrade\n\n')

    parser = argparse.ArgumentParser(
        description='Tag Mint transactions based on itemized Amazon history.')
    define_cli_args(parser)
    args = parser.parse_args()

    if args.version:
        print('mint-amazon-tagger {}\nBy: Jeff Prouty'.format(VERSION))
        exit(0)

    # mint_client = MintClient(
        # email=args.mint_email,
        # password=args.mint_password,
        # session_path=args.session_path,
        # headless=args.headless,
        # mfa_method=args.mint_mfa_method,
        # wait_for_sync=args.mint_wait_for_sync,
        # progress_factory=indeterminate_progress_cli)

    if args.dry_run:
        logger.info('\nDry Run; no modifications being sent to BQ.\n')

    def on_critical(msg):
        logger.critical(msg)
        exit(1)

    # results = tagger.create_updates(
        # args, mint_client,
        # on_critical=on_critical,
        # indeterminate_progress_factory=indeterminate_progress_cli,
        # determinate_progress_factory=determinate_progress_cli,
        # counter_progress_factory=counter_progress_cli)

    bq_client = BigQueryClient(progress_factory=indeterminate_progress_cli)

    results = bq_importer.create_updates(
        args, bq_client,
        on_critical=on_critical,
        indeterminate_progress_factory=indeterminate_progress_cli,
        determinate_progress_factory=determinate_progress_cli,
        counter_progress_factory=counter_progress_cli)

    if not results.success:
        logger.critical('Uncaught error from create_updates. Exiting')
        exit(1)

    log_amazon_stats(results.items, results.orders, results.refunds)
    log_processing_stats(results.stats)


def log_amazon_stats(items, orders, refunds):
    logger.info('\nAmazon Stats:')
    if len(orders) == 0 or len(items) == 0:
        logger.info('\tThere were not Amazon orders/items!')
        return
    logger.info('{} unmatched orders and {} unmatched items'.format(
        len([o for o in orders if not o.items_matched]),
        len([i for i in items if not i.matched])))

    first_order_date = min([o.order_date for o in orders])
    last_order_date = max([o.order_date for o in orders])
    logger.info('Orders ranging from {} to {}'.format(
        first_order_date, last_order_date))

    per_item_totals = [i.item_total for i in items]
    per_order_totals = [o.total_charged for o in orders]

    logger.info('{} total spend'.format(
        micro_usd_to_usd_string(sum(per_order_totals))))

    logger.info('{} avg order total (range: {} - {})'.format(
        micro_usd_to_usd_string(sum(per_order_totals) / len(orders)),
        micro_usd_to_usd_string(min(per_order_totals)),
        micro_usd_to_usd_string(max(per_order_totals))))
    logger.info('{} avg item price (range: {} - {})'.format(
        micro_usd_to_usd_string(sum(per_item_totals) / len(items)),
        micro_usd_to_usd_string(min(per_item_totals)),
        micro_usd_to_usd_string(max(per_item_totals))))

    if refunds:
        first_refund_date = min(
            [r.refund_date for r in refunds if r.refund_date])
        last_refund_date = max(
            [r.refund_date for r in refunds if r.refund_date])
        logger.info('\n{} refunds dating from {} to {}'.format(
            len(refunds), first_refund_date, last_refund_date))

        per_refund_totals = [r.total_refund_amount for r in refunds]

        logger.info('{} total refunded'.format(
            micro_usd_to_usd_string(sum(per_refund_totals))))


def log_processing_stats(stats):
    logger.info(
        'Stats: '.format(**stats))


def print_unmatched(amzn_obj):
    proposed_mint_desc = mint.summarize_title(
        [i.get_title() for i in amzn_obj.items]
        if amzn_obj.is_debit else [amzn_obj.get_title()],
        '{}{}: '.format(
            amzn_obj.website, '' if amzn_obj.is_debit else ' refund'))
    logger.warning('{}'.format(proposed_mint_desc))
    logger.warning('\t{}\t{}\t{}'.format(
        amzn_obj.transact_date()
        if amzn_obj.transact_date()
        else 'Never shipped!',
        micro_usd_to_usd_string(amzn_obj.transact_amount()),
        amazon.get_invoice_url(amzn_obj.order_id)))
    logger.warning('')


if __name__ == '__main__':
    main()
