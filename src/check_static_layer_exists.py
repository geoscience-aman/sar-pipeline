import json
from sar_pipeline.aws.preparation.burst_utils import (
    get_burst_ids_and_start_times_for_scene_from_asf,
    check_burst_products_exists_in_s3,
)

def lambda_handler(event, context):
    try:
        scene = event["scene"]
        product = event.get("product", "RTC_STATIC_S1")
        s3_bucket = event.get("s3_bucket", "deant-data-public-dev")
        s3_project_folder = event.get("s3_project_folder")
        collection = event.get("collection", "s1_rtc_c1")
        make_existing_products = event.get("make_existing_products", False)

        burst_id_list, burst_st_list = get_burst_ids_and_start_times_for_scene_from_asf(scene)

        existing_bursts = check_burst_products_exists_in_s3(
            product=product,
            burst_id_list=burst_id_list,
            burst_st_list=burst_st_list,
            s3_bucket=s3_bucket,
            s3_project_folder=s3_project_folder,
            collection=collection,
            make_existing_products=make_existing_products 
        )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "scene": scene,
                "existing_bursts": existing_bursts
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
