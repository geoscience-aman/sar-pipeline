from pathlib import Path

from sar_pipeline.nci.preparation.orbits import find_orbits
from dem_handler.dem.cop_glo30 import get_cop30_dem_for_bounds


def get_orbits_nci(
    orbit_type: str | None,
    sensor: str,
    nci_orbit_dir: Path = Path("/g/data/fj7/Copernicus/Sentinel-1/"),
) -> list[Path]:
    """For a given orbit type and sensor, compile the relevant orbit files

    Parameters
    ----------
    orbit_type : str | None
        One of 'POE', 'RES', or None. If None, both POE and RES orbits will be included
    sensor : str
        Sensor (e.g. S1A or S1B) to search. Typically extracted from the scene ID
    nci_orbit_dir : Path, optional
        The path containing orbit files on the NCI, by default Path("/g/data/fj7/Copernicus/Sentinel-1/")
    Returns
    -------
    list[Path]
        List of orbit files on NCI matching search criteria

    Raises
    ------
    ValueError
        Invalid orbit type. Must be one of 'POE', 'RES' or None
    """

    # Constants for NCI
    POE_DIR = "POEORB"
    RES_DIR = "RESORB"

    if orbit_type == "POE":
        orbit_type_directories = [POE_DIR]
    elif orbit_type == "RES":
        orbit_type_directories = [RES_DIR]
    elif orbit_type is None:
        orbit_type_directories = [RES_DIR, POE_DIR]
    else:
        raise ValueError("orbit_type must be one of 'POE', 'RES', or None")

    nci_orbit_directories = [
        nci_orbit_dir / orbit_dir / sensor for orbit_dir in orbit_type_directories
    ]

    orbits = find_orbits(nci_orbit_directories)

    return orbits


def get_dem_nci(
    scene: Path, scene_bounds: tuple[float, float, float, float], output_dir: Path
) -> Path:
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
    dem_file = output_dir / f"{scene.stem}.tif"

    if not dem_file.exists():
        _, _ = get_cop30_dem_for_bounds(scene_bounds, dem_file, ellipsoid_heights=True)

    return dem_file
