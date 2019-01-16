add_python_test(basic PLUGIN wholetale)
add_python_test(harvester
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/harvester_test01.json
  plugins/wholetale/dataone_listFiles.json
  plugins/wholetale/test_list_files.txt
)
add_python_test(image PLUGIN wholetale)
add_python_test(tale PLUGIN wholetale)
add_python_test(instance PLUGIN wholetale)
add_python_test(constants PLUGIN wholetale)
add_python_test(utils PLUGIN wholetale)
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
add_python_test(dataverse
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/dataverse_lookup.txt
  plugins/wholetale/dataverse_listFiles.json
)
add_python_test(integration PLUGIN wholetale)
add_python_test(repository
  PLUGIN wholetale
)
add_python_test(workspace
  PLUGIN wholetale
)
add_python_test(dataset
  PLUGIN wholetale
  EXTERNAL_DATA
  plugins/wholetale/dataset_register.txt
)
add_python_style_test(python_static_analysis_wholetale
                      "${PROJECT_SOURCE_DIR}/plugins/wholetale/server")
