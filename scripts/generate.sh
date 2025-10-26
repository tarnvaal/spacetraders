npx --yes @openapitools/openapi-generator-cli@7.5.0 generate \
  -i https://spacetraders.io/SpaceTraders.json \
  -g python \
  -o /home/tarnv/spacetraders/packages/spacetraders_python_sdk \
  --additional-properties=packageName="spacetraders_python_sdk",projectName="spacetraders-python-sdk",packageVersion="0.1.0"