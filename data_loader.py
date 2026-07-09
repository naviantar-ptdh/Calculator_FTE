ValueError: This app has encountered an error. The original error message is redacted to prevent data leaks. Full error details have been recorded in the logs (if you're on Streamlit Cloud, click on 'Manage app' in the lower right of your app).
Traceback:
File "/mount/src/calculator_fte/app.py", line 253, in <module>
    main()
    ~~~~^^
File "/mount/src/calculator_fte/app.py", line 119, in main
    backend = get_backend()
File "/home/adminuser/venv/lib/python3.14/site-packages/streamlit/runtime/caching/cache_utils.py", line 281, in __call__
    return self._get_or_create_cached_value(args, kwargs, spinner_message)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/home/adminuser/venv/lib/python3.14/site-packages/streamlit/runtime/caching/cache_utils.py", line 326, in _get_or_create_cached_value
    return self._handle_cache_miss(cache, value_key, func_args, func_kwargs)
           ~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/home/adminuser/venv/lib/python3.14/site-packages/streamlit/runtime/caching/cache_utils.py", line 385, in _handle_cache_miss
    computed_value = self._info.func(*func_args, **func_kwargs)
File "/mount/src/calculator_fte/app.py", line 67, in get_backend
    return load_backend_data()
File "/mount/src/calculator_fte/data_loader.py", line 148, in load_backend_data
    return parse_backend(raw)
File "/mount/src/calculator_fte/data_loader.py", line 58, in parse_backend
    headers[2]: float(str(_cell(raw, curr, 2)).replace(",", ".")),
                ~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
