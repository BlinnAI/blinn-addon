import ast
import io
import tokenize


def remove_comments(source):
    io_obj = io.StringIO(source)
    out = ""
    prev_toktype = tokenize.INDENT
    last_lineno = -1
    last_col = 0
    for tok in tokenize.generate_tokens(io_obj.readline):
        token_type = tok[0]
        token_string = tok[1]
        start_line, start_col = tok[2]
        end_line, end_col = tok[3]
        if start_line > last_lineno:
            last_col = 0
        if start_col > last_col:
            out += " " * (start_col - last_col)
        if token_type == tokenize.COMMENT:
            pass  # Skip comments
        elif token_type == tokenize.STRING:
            if (
                prev_toktype != tokenize.INDENT
                and prev_toktype != tokenize.NEWLINE
                and start_col > 0
            ):
                out += token_string  # Preserve non-docstring strings
            else:
                out += token_string  # Optionally adjust to remove docstrings here if needed
        else:
            out += token_string
        prev_toktype = token_type
        last_col = end_col
        last_lineno = end_line
    return out


def remove_docstrings(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            node.value.value = ""
    return tree


def clean_script(script):
    source_no_comments = remove_comments(script)
    tree = ast.parse(source_no_comments)
    cleaned_tree = remove_docstrings(tree)
    cleaned_script = ast.unparse(cleaned_tree)

    return cleaned_script.strip()
