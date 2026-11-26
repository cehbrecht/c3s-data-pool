# Synthetic C3S catalogs

These small, uncompressed CSV files use representative CMIP6 directory layouts,
filenames and additional catalog columns. They are hand-written test fixtures,
not extracts from the published manifests. Versions and tiny byte sizes are
synthetic; no actual NetCDF or climate data is included.

- `c3s-cmip6.csv`: historical monthly temperature and precipitation.
- `c3s-cmip6-decadal.csv`: monthly temperature from two decadal initialization years.

The integration tests generate matching synthetic source files, including one
source symlink, under a temporary DKRZ-style tree. Both collections share the
source pool and retain separate versioned target paths.
