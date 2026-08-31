@echo off
cd /d "%~dp0"

set ANNOTATOR_DATA_ROOT=..\data\Tile_X_0003_Y_0017_Z_0000
set ANNOTATOR_ANNOTATIONS_ROOT=..\data\annotations
set ANNOTATOR_ROLES_FILE=..\configs\roles.json
set ANNOTATOR_CLASSES_FILE=..\configs\classes.json

set ANNOTATOR_S3_DATA_BUCKET=aind-scratch-data
set ANNOTATOR_S3_DATA_PREFIX=proteomics_annotations/data
set ANNOTATOR_S3_OUTPUT_BUCKET=aind-scratch-data
set ANNOTATOR_S3_OUTPUT_PREFIX=proteomics_annotations/annotations
set ANNOTATOR_S3_PROFILE=aind_dev_sso

python -m aind_proteomics_annotator
