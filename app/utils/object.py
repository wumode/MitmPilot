import ast
import dis
import inspect
import textwrap
from collections.abc import Callable
from types import FunctionType
from typing import Any, get_type_hints


class ObjectUtils:
    @staticmethod
    def is_obj(obj: Any):
        if isinstance(obj, list) or isinstance(obj, dict) or isinstance(obj, tuple):
            return True
        elif (
            isinstance(obj, int)
            or isinstance(obj, float)
            or isinstance(obj, bool)
            or isinstance(obj, bytes)
            or isinstance(obj, str)
        ):
            return False
        return True

    @staticmethod
    def is_objstr(obj: Any):
        if not isinstance(obj, str):
            return False
        return (
            str(obj).startswith("{")
            or str(obj).startswith("[")
            or str(obj).startswith("(")
        )

    @staticmethod
    def arguments(func: Callable[..., Any]) -> int:
        """Returns the number of arguments of the function."""
        signature = inspect.signature(func)
        parameters = signature.parameters

        return len(list(parameters.keys()))

    @staticmethod
    def check_method(func: Callable[..., Any]) -> bool:
        """Checks if the function is implemented."""
        try:
            src = inspect.getsource(func)
            tree = ast.parse(textwrap.dedent(src))
            node = tree.body[0]
            # Not a regular function definition (e.g., lambda, built-in function, or parsing failed)
            # Assume the function is implemented by default
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return True
            body = node.body

            for stmt in body:
                # Skip pass
                if isinstance(stmt, ast.Pass):
                    continue
                # Skip docstring or ...
                if isinstance(stmt, ast.Expr):
                    expr = stmt.value
                    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
                        continue
                    if isinstance(expr, ast.Constant) and expr.value is Ellipsis:
                        continue
                # Check for raise NotImplementedError
                if isinstance(stmt, ast.Raise):
                    exc = stmt.exc
                    if (
                        isinstance(exc, ast.Call)
                        and getattr(exc.func, "id", None) == "NotImplementedError"
                    ):
                        continue
                    if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
                        continue
                return True
            return False
        except Exception as err:
            print(err)
            # If source code analysis fails, perform bytecode analysis

            # For methods, get the underlying function
            if hasattr(func, "__func__"):
                func = func.__func__

            # Check if the function has a __code__ attribute
            if not hasattr(func, "__code__"):
                # If not, we can't analyze it, assume it's implemented
                return True

            code_obj = func.__code__
            instructions = list(dis.get_instructions(code_obj))
            # Check if it's a simple structure that only returns None
            if len(instructions) == 2:
                first, second = instructions
                if first.opname == "LOAD_CONST" and second.opname == "RETURN_VALUE":
                    # Verify if the loaded constant is None
                    const_index = first.arg
                    if const_index is None:
                        return False
                    if (
                        const_index < len(code_obj.co_consts)
                        and code_obj.co_consts[const_index] is None
                    ):
                        # Unimplemented empty function
                        return False
            # Otherwise, assume it's implemented
            return True

    @staticmethod
    def check_signature(func: FunctionType, *args) -> bool:
        """Checks if the output matches the function's argument types."""
        # Get function parameter information
        signature = inspect.signature(func)
        parameters = signature.parameters
        if len(args) != len(parameters):
            return False
        try:
            # 获取解析后的类型提示
            type_hints = get_type_hints(func)
        except TypeError:
            type_hints = {}
        for arg, (param_name, param) in zip(args, parameters.items(), strict=False):
            # Prefer parsed type hints
            param_type = type_hints.get(param_name, None)
            if param_type is None:
                # Handle raw annotations (possibly string or Cython types)
                param_annotation = param.annotation
                if param_annotation is inspect.Parameter.empty:
                    continue
                # Handle string type annotations
                if isinstance(param_annotation, str):
                    # Attempt to parse string as actual type
                    module = inspect.getmodule(func)
                    global_vars = module.__dict__ if module else globals()
                    try:
                        param_type = eval(param_annotation, global_vars)
                    except Exception as err:
                        print(str(err))
                        continue
                else:
                    param_type = param_annotation
            if param_type is None:
                continue
            if not isinstance(arg, param_type):
                return False
        return True
