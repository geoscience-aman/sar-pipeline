import click
import logging
from pathlib import Path
import shutil
from shapely.geometry import Polygon
from s1reader import s1_info

from sar_pipeline.aws.preparation.scenes import (
    download_slc_from_asf,
    download_slc_from_cdse,
)
from sar_pipeline.aws.preparation.orbits import download_orbits
from sar_pipeline.aws.preparation.static_layers import (
    check_static_layers_in_s3,
    make_static_layer_base_url,
)

from sar_pipeline.aws.preparation.config import RTCConfigManager
from sar_pipeline.aws.metadata.stac import BurstH5toStacManager

from dem_handler.dem.cop_glo30 import get_cop30_dem_for_bounds
from sar_pipeline.utils.s3upload import push_files_in_folder_to_s3


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@click.command()
@click.option(
    "--scene",
    type=str,
    required=True,
    help="scene id. E.g. S1A_IW_SLC__1SSH_20220101T124744_20220101T124814_041267_04E7A2_1DAD",
)
@click.option(
    "--burst_id_list",
    required=False,
    multiple=True,
    help="List of burst IDs separated by space. e.g. t070_149815_iw2 t070_149815_iw3",
)
@click.option(
    "--resolution",
    required=True,
    type=int,
    help="The desired resolution of the final product (metres)",
)
@click.option(
    "--output-crs",
    required=False,
    default="",
    help="The output CRS as an integer. e.g. 3031. If [None,'UTM','utm'] the default UTM zone for scene/burst center is used (polar stereo at lat>75).",
)
@click.option("--dem", required=True, type=click.Choice(["cop_glo30"]))
@click.option(
    "--product",
    required=True,
    type=click.Choice(["RTC_S1", "RTC_S1_STATIC"]),
    help="The product to be made",
)
@click.option(
    "--download-folder",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Path to the folder where downloaded files should go",
)
@click.option(
    "--scratch-folder",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Path to the folder where scratch files go",
)
@click.option(
    "--out-folder",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Path to the folder where final products will be written",
)
@click.option(
    "--run-config-save-path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to where the RTC/opera config wil be saved",
)
@click.option(
    "--link-static-layers",
    required=False,
    is_flag=True,
    default=False,
    help="If static layers should be linked to RTC_S1 products in the"
    "STAC metadata. A url to the static layer collection will be added"
    "to the run config file.",
)
@click.option(
    "--linked-static-layers-s3-bucket",
    required=False,
    type=str,
    help="S3 bucket containing the RTC_S1_STATIC data that will be linked to the RTC_S1 bursts.",
)
@click.option(
    "--linked-static-layers-collection",
    required=False,
    type=str,
    help="Collection of RTC_S1_STATIC data that will be linked to the RTC_S1 bursts.",
)
@click.option(
    "--linked-static-layers-s3-project-folder",
    required=False,
    type=str,
    help="Project folder containing the RTC_S1_STATIC data that will be linked to the RTC_S1 bursts. "
    "Expected for linked files path is : s3_bucket/s3_project_folder/collection/burst_id/*files",
)
@click.option(
    "--scene_data_source",
    required=False,
    default="CDSE",
    type=click.Choice(["ASF", "CDSE"]),
    help="Where to download the scene from.",
)
@click.option(
    "--orbit_data_source",
    required=False,
    default="CDSE",
    type=click.Choice(["ASF", "CDSE"]),
    help="Where to download the scene from.",
)
@click.option("--make-folders", required=False, default=True, help="Create folders")
def get_data_for_scene_and_make_run_config(
    scene,
    burst_id_list,
    resolution,
    output_crs,
    dem,
    product,
    download_folder,
    scratch_folder,
    out_folder,
    run_config_save_path,
    link_static_layers,
    linked_static_layers_s3_bucket,
    linked_static_layers_collection,
    linked_static_layers_s3_project_folder,
    scene_data_source,
    orbit_data_source,
    make_folders,
):
    """Download the required data for the RTC/opera and create a configuration
    file for the run that points to appropriate files and has the required settings
    """
    logger.info(f"Downloading data for scene : {scene}")
    logger.info(f"Data source for scene download : {scene_data_source}")
    logger.info(f"Data source for orbit download : {orbit_data_source}")

    # make the base .yaml for RTC processing
    if product == "RTC_S1":
        RTC_RUN_CONFIG = RTCConfigManager(base_config="S1_RTC.yaml")
    elif product == "RTC_S1_STATIC":
        RTC_RUN_CONFIG = RTCConfigManager(base_config="S1_RTC_STATIC.yaml")
    else:
        raise ValueError("product must be S1_RTC or S1_RTC_STATIC")

    if make_folders:
        logger.info(f"Making output folders if not existing")
        download_folder.mkdir(parents=True, exist_ok=True)
        out_folder.mkdir(parents=True, exist_ok=True)
        scratch_folder.mkdir(parents=True, exist_ok=True)
        run_config_save_path.parent.mkdir(parents=True, exist_ok=True)

    # download the SLC and get scene metadata from asf
    logger.info(f"Downloading SLC for scene : {scene}")
    scene_folder = download_folder / "scenes"
    if scene_data_source == "ASF":
        SCENE_PATH, asf_scene_metadata = download_slc_from_asf(scene, scene_folder)
        scene_polygon = Polygon(asf_scene_metadata.geometry["coordinates"][0])
        polarisation_list = asf_scene_metadata.properties["polarization"].split("+")
        input_scene_url = asf_scene_metadata.properties["url"]
    if scene_data_source == "CDSE":
        SCENE_PATH, cdse_scene_metadata = download_slc_from_cdse(scene, scene_folder)
        scene_polygon = Polygon(cdse_scene_metadata["geometry"]["coordinates"][0])
        polarisation_list = cdse_scene_metadata["properties"]["polarisation"].split("&")
        input_scene_url = cdse_scene_metadata["properties"]["services"]["download"][
            "url"
        ]

    # check the static layers exist
    if link_static_layers:

        if not burst_id_list:
            # list of bursts not provided, get them from the downloaded file
            burst_id_list = []
            logger.info(f"Getting all burst ids from the scene zip file")
            logger.info(f"Scene polarisations : {polarisation_list}")
            for pol in polarisation_list:
                burst_id_list += [
                    str(b.burst_id)
                    for b in s1_info.get_bursts(SCENE_PATH, pol=pol.lower())
                ]
            burst_id_list = list(set(burst_id_list))  # remove duplicates
            logger.info(f"{len(burst_id_list)} bursts found for scene")

        logger.info(f"Checking static layers exist for bursts in scene : {scene}")
        check_static_layers_in_s3(
            scene=scene,
            burst_id_list=burst_id_list,
            static_layers_s3_bucket=linked_static_layers_s3_bucket,
            static_layers_collection=linked_static_layers_collection,
            static_layers_s3_project_folder=linked_static_layers_s3_project_folder,
        )

    # # download the orbits
    logger.info(f"Downloading Orbits for scene : {scene}")
    orbit_folder = download_folder / "orbits"
    ORBIT_PATHS = download_orbits(
        sentinel_file=scene + ".SAFE", save_dir=orbit_folder, source=orbit_data_source
    )
    if len(ORBIT_PATHS) > 1:
        raise ValueError(
            f"{len(ORBIT_PATHS)} orbit paths found for scene. Expecting 1."
        )
    logger.info(f"File downloaded to : {ORBIT_PATHS[0]}")

    # # download the dem
    dem_folder = download_folder / "dem"
    DEM_PATH = dem_folder / f"{scene}_dem.tif"
    bounds = scene_polygon.bounds

    logger.info(f"Downloading DEM type `{dem}` to path : {DEM_PATH}")
    get_cop30_dem_for_bounds(
        bounds=bounds,
        save_path=DEM_PATH,
        ellipsoid_heights=True,
        adjust_at_high_lat=True,
        buffer_pixels=None,
        buffer_degrees=0.3,
        cop30_folder_path=dem_folder,
        geoid_tif_path=dem_folder / f"{scene}_geoid.tif",
        download_dem_tiles=True,
        download_geoid=True,
    )

    # Update input and ancillary data
    logger.info(f"Updating the run config for scene")
    gk = "runconfig.groups"
    RTC_RUN_CONFIG.set(f"{gk}.input_file_group.safe_file_path", [str(SCENE_PATH)])
    RTC_RUN_CONFIG.set(
        f"{gk}.input_file_group.source_data_access",
        input_scene_url,
    )
    RTC_RUN_CONFIG.set(f"{gk}.input_file_group.orbit_file_path", [str(ORBIT_PATHS[0])])
    RTC_RUN_CONFIG.set(f"{gk}.dynamic_ancillary_file_group.dem_file", str(DEM_PATH))

    # set the dem input source
    if dem == "cop_glo30":
        demSource = "https://registry.opendata.aws/copernicus-dem/"
        RTC_RUN_CONFIG.set(
            f"{gk}.dynamic_ancillary_file_group.dem_file_description", demSource
        )

    if burst_id_list:
        # specify bursts if provided
        RTC_RUN_CONFIG.set(f"{gk}.input_file_group.burst_id", burst_id_list)

    # Update Outputs
    RTC_RUN_CONFIG.set(f"{gk}.product_group.output_dir", str(out_folder))
    RTC_RUN_CONFIG.set(f"{gk}.product_group.scratch_path", str(scratch_folder))
    if product == "RTC_S1_STATIC":
        # TODO YYYYMMDD
        RTC_RUN_CONFIG.set(
            f"{gk}.product_group.rtc_s1_static_validity_start_date", 20010101
        )

    if link_static_layers:
        # add the static layer base url
        static_layer_base_url = make_static_layer_base_url(
            linked_static_layers_s3_bucket,
            linked_static_layers_collection,
            linked_static_layers_s3_project_folder,
        )
        logger.info(f"static layer base url : {static_layer_base_url}")
        RTC_RUN_CONFIG.set(
            f"{gk}.product_group.static_layers_data_access", str(static_layer_base_url)
        )

    # set the polarisation
    POLARIZATION_TYPE = (
        "dual-pol" if len(polarisation_list) > 1 else "co-pol"
    )  # string for template value
    RTC_RUN_CONFIG.set(f"{gk}.processing.polarization", POLARIZATION_TYPE)

    # update the burst resolution
    bk = "runconfig.groups.processing.geocoding.bursts_geogrid"
    RTC_RUN_CONFIG.set(f"{bk}.x_posting", int(resolution))
    RTC_RUN_CONFIG.set(f"{bk}.y_posting", int(resolution))
    RTC_RUN_CONFIG.set(f"{bk}.x_snap", int(resolution))
    RTC_RUN_CONFIG.set(f"{bk}.y_snap", int(resolution))

    # update the burst crs if it has been set and is not UTM | utm
    if output_crs and (output_crs not in ["utm", "UTM"]):
        RTC_RUN_CONFIG.set(f"{bk}.output_epsg", int(output_crs))

    # save the config
    logger.info(f"Saving config to : {run_config_save_path}")
    RTC_RUN_CONFIG.save(run_config_save_path)


@click.command()
@click.option(
    "--results-folder",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Path to the folder containing the burst outputs from RTC/opera",
)
@click.option(
    "--run-config-path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to the config path used to run RTC opera",
)
@click.option(
    "--product",
    required=True,
    type=click.Choice(["RTC_S1", "RTC_S1_STATIC"]),
    help="The product being made. Determines bucket structure",
)
@click.option(
    "--collection",
    required=True,
    type=str,
    help="The collection the products belong to. e.g. s1_rtc_c1",
)
@click.option(
    "--s3-bucket", required=True, type=str, help="The bucket to upload the files"
)
@click.option(
    "--s3-project-folder",
    required=True,
    type=str,
    help="The folder within the bucket to upload the files. Note the "
    "final path follows the patter in the description of this function.",
)
@click.option(
    "--link-static-layers",
    required=False,
    is_flag=True,
    default=False,
    help="If static layers should be linked to RTC_S1 products in the"
    "STAC metadata. If set, the url to the static layer collection will "
    "be read in from the .h5 output from the rtc_s1.py process.",
)
def make_rtc_opera_stac_and_upload_bursts(
    results_folder,
    run_config_path,
    product,
    collection,
    s3_bucket,
    s3_project_folder,
    link_static_layers,
):
    """makes STAC metadata for opera-rtc and uploads them to a desired s3 bucket.
    The final path in s3 will follow the following pattern:
    s3_bucket/s3_folder/collection/burst_id/burst_year/burst_month/burst_day/*files
    """

    # iterate through the burst directory and create STAC metadata
    burst_folders = [x for x in results_folder.iterdir() if x.is_dir()]
    for i, burst_folder in enumerate(burst_folders):
        logger.info(
            f"Making STAC metadata for burst {i+1} of {len(burst_folders)} : {burst_folder}"
        )
        # copy the run config file to the burst folder
        shutil.copy(run_config_path, burst_folder / run_config_path.name)
        # load in the .h5 file containing metadata for each burst
        burst_h5_files = list(burst_folder.glob("*.h5"))
        if len(burst_h5_files) != 1:
            raise ValueError(
                f"{len(burst_h5_files)} .h5 files found. Expecting 1 in : {burst_folder}"
            )
        burst_h5_filepath = burst_folder / burst_h5_files[0]
        # make the stac metadata from the .h5 metadata
        logging.info(f"Making stac metadata from .h5 file")
        # initialise the class to convert data from the .h5 to a stac doc
        burst_stac_manager = BurstH5toStacManager(
            h5_filepath=burst_h5_filepath,
            product=product,
            collection=collection,
            s3_bucket=s3_bucket,
            s3_project_folder=s3_project_folder,
        )
        # make the stac item based
        burst_stac_manager.make_stac_item_from_h5()
        # add properties to the stac doc
        # TODO finalise stac metadata
        burst_stac_manager.add_properties_from_h5()
        # add the assets to the stac doc
        burst_stac_manager.add_assets_from_folder(burst_folder)
        # add additional links that will rarely change
        burst_stac_manager.add_fixed_links()
        # add links that can change
        burst_stac_manager.add_dynamic_links_from_h5()
        # add the link to self/metadata
        if link_static_layers:
            # link to static layer metadata is in the .h5 file
            # use this to map assets to the file
            burst_stac_manager.add_linked_static_layer_assets_and_link()
        stac_filename = "metadata.json"
        burst_stac_manager.add_self_link(filename=stac_filename)
        # save the metadata
        burst_stac_manager.save(burst_folder / stac_filename)
        # TODO validate the stac item when finalised
        # burst_stac_manager.item.validate()
        # push folder to S3
        push_files_in_folder_to_s3(
            burst_folder, s3_bucket, burst_stac_manager.burst_s3_subfolder
        )
