add_python_test(basic PLUGIN wholetale)
add_python_test(accounts PLUGIN wholetale)
add_python_test(oauth PLUGIN wholetale)
add_python_test(harvester
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/harvester_test01.json
  plugins/wholetale/dataone_listFiles.json
  plugins/wholetale/test_list_files.txt
)
add_python_test(image PLUGIN wholetale)
add_python_test(tale
  PLUGIN wholetale
)
add_python_test(import
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/604126f45f6bb2c4c997e967.zip
  plugins/wholetale/61f18414fdfd5791fbb61b7b.zip
  plugins/wholetale/Reporter_Cell_Line_14-3QDC.zip
  plugins/wholetale/tale_import_binder.txt
  plugins/wholetale/tale_import_zip.txt
  plugins/wholetale/tale_import_dsRootPath.txt
  plugins/wholetale/tale_import_rrzip.txt
)
add_python_test(import_failures PLUGIN wholetale)
add_python_test(instance PLUGIN wholetale)
add_python_test(constants PLUGIN wholetale)
add_python_test(utils PLUGIN wholetale)
add_python_test(manifest
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/manifest_mock_catalog.json
  plugins/wholetale/reference_dataset.json
)
add_python_test(dataone_register
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/test_find_resource_pid.txt
  plugins/wholetale/test_get_package_list_flat.txt
  plugins/wholetale/test_get_package_list_nested.txt
  plugins/wholetale/test_cn_switch.txt
  plugins/wholetale/dataone_register_test01.json
  plugins/wholetale/DataONE_register_nested.txt
)
add_python_test(zenodo
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/zenodo_hierarchy.txt
  plugins/wholetale/zenodo_manifest.txt
  plugins/wholetale/zenodo_lookup.txt
)
add_python_test(dataverse
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/dataverse_lookup.txt
  plugins/wholetale/dataverse_hierarchy.txt
  plugins/wholetale/dataverse_listFiles.json
)
add_python_test(integration
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/dataverse_integration.txt
  plugins/wholetale/dataone_integration.txt
)
add_python_test(repository
  PLUGIN wholetale
)
add_python_test(bdbag
  PLUGIN wholetale
)
add_python_test(dataset
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/dataset_register.txt
)
add_python_test(git PLUGIN wholetale)
add_python_test(publish PLUGIN wholetale)
add_python_test(notification PLUGIN wholetale)
add_python_test(globus PLUGIN wholetale)
add_python_test(sharing PLUGIN wholetale)
add_python_test(verificator PLUGIN wholetale)
add_python_test(deriva
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/Dataset_1-882P.zip
)
add_python_test(openicpsr
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/openicpsr_lookup.txt
  plugins/wholetale/openicpsr_login_flow.txt
  plugins/wholetale/openicpsr_import.txt
)
add_python_style_test(python_static_analysis_wholetale
                      "${PROJECT_SOURCE_DIR}/plugins/wholetale/server")
