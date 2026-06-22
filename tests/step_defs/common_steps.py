from pytest_bdd import given, then, parsers

@then(parsers.parse('the pipeline log shows "{message}"'))
def pipeline_log_shows(workspace, message):
    """
    Generic step to verify that the subprocess stdout/stderr contains a specific message.
    Automatically handles cross-platform slashes and placeholder replacements.
    """
    # Replace <path> with the actual temporary workspace directory
    expected = message.replace("<path>", str(workspace.base_dir)).replace('\\', '/')
    output = workspace.stdout.replace('\\', '/') + "\n" + workspace.stderr.replace('\\', '/')

    # Handle the <application-name> placeholder by checking for prefix match
    if "<application-name>" in expected:
        prefix = expected.split("<application-name>")[0]
        found = any(line.endswith(prefix) or prefix in line for line in output.splitlines())
    else:
        found = expected in output

    if not found:
        # Fallback if <path> should be ignored dynamically
        clean_msg = message.replace("<path>", "").replace('\\', '/')
        if "<application-name>" in clean_msg:
            prefix = clean_msg.split("<application-name>")[0]
            found = any(prefix in line for line in output.splitlines())
        else:
            found = clean_msg in output

    assert found, f"Expected message not found in logs: {message}\nOutput: {output}"

@given(parsers.parse('the pipeline has {param} set to "{value}"'))
def set_pipeline_param(workspace, param, value):
    if not hasattr(workspace, 'extra_env'):
        workspace.extra_env = {}
    workspace.extra_env[param] = value
