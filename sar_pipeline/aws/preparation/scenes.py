import asf_search
import os
from pathlib import Path
import logging
import zipfile
from cdsetool.query import query_features
from cdsetool.credentials import Credentials
from cdsetool.download import download_features
from cdsetool.monitor import StatusMonitor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MissingCredentialsError(Exception):
    """Exception raised when no credentials are supplied."""

    pass


def download_slc_from_asf(
    scene: str,
    download_folder: Path,
    make_folder: bool = True,
    unzip: bool = True,
    asf_login: str | None = None,
    asf_pass: str | None = None,
):

    logger.info(f'Searching ASF for scene')
    
    search_results = asf_search.granule_search(
        [scene], asf_search.ASFSearchOptions(processingLevel="SLC")
    )

    # ensure only one slc found
    if len(search_results) != 1:
        raise ValueError(f"Expected 1 SLC, found {len(search_results)} for scene : {scene}")
    asf_scene_metadata = search_results[0]
    scene_name = asf_scene_metadata.properties["sceneName"]

    # Authenticate. If credentials not supplied search the environment variables
    if asf_login is None and asf_pass is None:
        asf_login = os.environ["EARTHDATA_LOGIN"]
        asf_pass = os.environ["EARTHDATA_PASSWORD"]
        if not asf_login or asf_pass:
            err_string = (
                "No credentials supplied. Please provide a asf_login and asf_pass "
                "or set the EARTHDATA_LOGIN and EARTHDATA_PASSWORD environment variables"
            )
            MissingCredentialsError(err_string)

    session = asf_search.ASFSession()
    session.auth_with_creds(asf_login, asf_pass)

    if make_folder:
        os.makedirs(download_folder, exist_ok=True)

    logger.info(f"Downloading : {scene_name}")
    asf_scene_metadata.download(path=download_folder, session=session)
    scene_zip_path = download_folder / f"{scene_name}.zip"

    scene_safe_path = scene_zip_path.with_suffix(".SAFE")
    if unzip and not os.path.exists(scene_safe_path):
        logger.info(f"unzipping scene to {scene_safe_path}")
        with zipfile.ZipFile(scene_zip_path, "r") as zip_ref:
            zip_ref.extractall(download_folder)
        return scene_safe_path, asf_scene_metadata
    else:
        return scene_zip_path, asf_scene_metadata


def download_slc_from_cdse(
    scene: str,
    download_folder: Path,
    make_folder: bool = True,
    unzip: bool = True,
    cdse_login: str | None = None,
    cdse_pass: str | None = None,
):
    
    # Authenticate. If credentials not supplied search the envrionment variables
    if cdse_login is None and cdse_pass is None:
        cdse_login = os.environ["EARTHDATA_LOGIN"]
        cdse_pass = os.environ["EARTHDATA_PASSWORD"]
        if not cdse_login or cdse_pass:
            err_string = (
                "No credentials supplied. Please provide a cdse_login and cdse_pass "
                "or set the CDSE_LOGIN and CDSE_PASSWORD environment variables"
            )
            MissingCredentialsError(err_string)

    if make_folder:
        os.makedirs(download_folder, exist_ok=True)

    logger.info(f'Searching CDSE for scene')

    features = query_features(
        "Sentinel1",
        {
            "processingLevel": "LEVEL1",
            "sensorMode": "IW",
            "productType": "IW_SLC__1S",
            "productIdentifier": scene
        },
    )

    if len(features) != 1:
        raise ValueError(f"Expected 1 SLC, found {len(features)} for scene : {scene}")

    list(
        download_features(
            features,
            download_folder,
            {
                "concurrency": 1,
                "monitor": StatusMonitor(),
                "credentials": Credentials(cdse_login, cdse_pass),
            },
        )
    )

    scene_zip_path = download_folder / f"{scene}.SAFE.zip"
    scene_safe_path = scene_zip_path.with_suffix('')
    if unzip and not os.path.exists(scene_safe_path):
        logger.info(f"unzipping scene to {scene_safe_path}")
        with zipfile.ZipFile(scene_zip_path, "r") as zip_ref:
            zip_ref.extractall(download_folder)
        return scene_safe_path
    else:
        return scene_zip_path

    