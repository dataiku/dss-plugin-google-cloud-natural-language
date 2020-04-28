# -*- coding: utf-8 -*-
import json
import logging
from google.cloud import language
from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.oauth2 import service_account
from typing import AnyStr, Dict, Union

from plugin_io_utils import (
    generate_unique, safe_json_loads, ErrorHandlingEnum, OutputFormatEnum)


# ==============================================================================
# CONSTANT DEFINITION
# ==============================================================================

DOCUMENT_TYPE = language.enums.Document.Type.PLAIN_TEXT
ENCODING_TYPE = language.enums.EncodingType.UTF8

API_EXCEPTIONS = (GoogleAPICallError, RetryError)

API_SUPPORT_BATCH = False
BATCH_RESULT_KEY = None
BATCH_ERROR_KEY = None
BATCH_INDEX_KEY = None
BATCH_ERROR_MESSAGE_KEY = None
BATCH_ERROR_TYPE_KEY = None

APPLY_AXIS = 1  # columns


# ==============================================================================
# FUNCTION DEFINITION
# ==============================================================================


def get_client(gcp_service_account_key=None):
    """
    Get a Google Natural Language API client from the service account key.
    """
    if gcp_service_account_key is None:
        return language.LanguageServiceClient()
    try:
        credentials = json.loads(gcp_service_account_key)
    except Exception as e:
        logging.error(e)
        raise ValueError("GCP service account key is not valid JSON.")
    credentials = service_account.Credentials.from_service_account_info(
        credentials)
    if hasattr(credentials, 'service_account_email'):
        logging.info("GCP service account loaded with email: %s" %
                     credentials.service_account_email)
    else:
        logging.info("Credentials loaded")
    client = language.LanguageServiceClient(credentials=credentials)
    return client


def format_named_entity_recognition(
    row: Dict,
    response_column: AnyStr,
    output_format: OutputFormatEnum = OutputFormatEnum.MULTIPLE_COLUMNS,
    column_prefix: AnyStr = "ner_api",
    error_handling: ErrorHandlingEnum = ErrorHandlingEnum.LOG
) -> Dict:
    """
    Format the API response for entity recognition to:
    - make sure response is valid JSON
    - expand results to multiple JSON columns (one by entity type)
    or put all entities as a list in a single JSON column
    """
    raw_response = row[response_column]
    response = safe_json_loads(raw_response, error_handling)
    if output_format == OutputFormatEnum.SINGLE_COLUMN:
        entity_column = generate_unique("entities", row.keys(), column_prefix)
        row[entity_column] = response.get("entities", '')
    else:
        entities = response.get("entities", [])
        available_entity_types = [
            n for n, m in language.enums.Entity.Type.__members__.items()]
        for n in available_entity_types:
            entity_type_column = generate_unique(
                "entity_type_" + n.lower(), row.keys(), column_prefix)
            row[entity_type_column] = [
                e.get("name") for e in entities if e.get("type", '') == n
            ]
            if len(row[entity_type_column]) == 0:
                row[entity_type_column] = ''
    return row


def format_sentiment_analysis(
    row: Dict,
    response_column: AnyStr,
    sentiment_scale: AnyStr = "ternary",
    column_prefix: AnyStr = "sentiment_api",
    error_handling: ErrorHandlingEnum = ErrorHandlingEnum.LOG
) -> Dict:
    """
    Format the API response for sentiment analysis to:
    - make sure response is valid JSON
    - expand results to two score and magnitude columns
    - scale the score according to predefined categorical or numerical rules
    """
    raw_response = row[response_column]
    response = safe_json_loads(raw_response, error_handling)
    sentiment_score_column = generate_unique(
        "score", row.keys(), column_prefix)
    sentiment_score_scaled_column = generate_unique(
        "score_scaled", row.keys(), column_prefix)
    sentiment_magnitude_column = generate_unique(
        "magnitude", row.keys(), column_prefix)
    sentiment = response.get("documentSentiment", {})
    sentiment_score = sentiment.get("score")
    magnitude_score = sentiment.get("magnitude")
    if sentiment_score is not None:
        row[sentiment_score_column] = float(sentiment_score)
        row[sentiment_score_scaled_column] = scale_sentiment_score(
            sentiment_score, sentiment_scale)
    else:
        row[sentiment_score_column] = None
        row[sentiment_score_scaled_column] = None
    if magnitude_score is not None:
        row[sentiment_magnitude_column] = float(magnitude_score)
    else:
        row[sentiment_magnitude_column] = None
    return row


def scale_sentiment_score(
    score: float,
    scale: AnyStr = 'ternary'
) -> Union[AnyStr, float]:
    """
    Scale the score according to predefined categorical or numerical rules
    """
    if scale == 'binary':
        return 'negative' if score < 0 else 'positive'
    elif scale == 'ternary':
        if score < -0.33:
            return 'negative'
        elif score > 0.33:
            return 'positive'
        else:
            return 'neutral'
    elif scale == 'quinary':
        if score < -0.66:
            return 'highly negative'
        elif score < -0.33:
            return 'negative'
        elif score < 0.33:
            return 'neutral'
        elif score < 0.66:
            return 'positive'
        else:
            return 'highly positive'
    elif scale == 'rescale_zero_to_one':
        return float((score+1.)/2)
    else:
        return float(score)


def format_text_classification(
    row: Dict,
    response_column: AnyStr,
    output_format: OutputFormatEnum = OutputFormatEnum.MULTIPLE_COLUMNS,
    num_categories: int = 3,
    column_prefix: AnyStr = "classification_api",
    error_handling: ErrorHandlingEnum = ErrorHandlingEnum.LOG
) -> Dict:
    """
    Format the API response for text classification to:
    - make sure response is valid JSON
    - expand results to multiple JSON columns (one by classification category)
    or put all categories as a list in a single JSON column
    """
    raw_response = row[response_column]
    response = safe_json_loads(raw_response, error_handling)
    if output_format == OutputFormatEnum.SINGLE_COLUMN:
        classification_column = generate_unique(
            "categories", row.keys(), column_prefix)
        row[classification_column] = response.get("categories", '')
    else:
        categories = sorted(
            response.get("categories", []), key=lambda x: x.get("confidence"),
            reverse=True)
        for n in range(num_categories):
            category_column = generate_unique(
                "category_" + str(n), row.keys(), column_prefix)
            confidence_column = generate_unique(
                "category_" + str(n) + "_confidence", row.keys(),
                column_prefix)
            if len(categories) > n:
                row[category_column] = categories[n].get("name", '')
                row[confidence_column] = categories[n].get("confidence")
            else:
                row[category_column] = ''
                row[confidence_column] = None
    return row