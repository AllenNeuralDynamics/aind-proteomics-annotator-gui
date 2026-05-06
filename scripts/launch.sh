export ANNOTATOR_DATA_ROOT=../data/Tile_X_0003_Y_0017_Z_0000
export ANNOTATOR_ANNOTATIONS_ROOT=../data/annotations
export ANNOTATOR_ROLES_FILE=../configs/roles.json
export ANNOTATOR_CLASSES_FILE=../configs/classes.json

# S3 config
export ANNOTATOR_S3_DATA_BUCKET=aind-scratch-data
export ANNOTATOR_S3_DATA_PREFIX=proteomics_annotations/data
export ANNOTATOR_S3_OUTPUT_BUCKET=aind-scratch-data
export ANNOTATOR_S3_OUTPUT_PREFIX=proteomics_annotations/annotations
export ANNOTATOR_S3_PROFILE=aind_dev_sso

python -m aind_proteomics_annotator