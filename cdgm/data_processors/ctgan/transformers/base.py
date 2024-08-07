"""BaseTransformer module."""
import abc
import contextlib
import inspect
import warnings
from functools import wraps

import numpy as np
import pandas as pd
import torch

@contextlib.contextmanager
def set_random_states(random_states, random_states_torch, method_name, set_model_random_state):
    """Context manager for managing the random state.
    Args:
        random_states (dict):
            Dictionary mapping each method to its current random state.
        method_name (str):
            Name of the method to set the random state for.
        set_model_random_state (function):
            Function to set the random state for the method.
    """
    original_np_state = np.random.get_state()
    random_np_state = random_states[method_name]
    np.random.set_state(random_np_state.get_state())

    original_torch_state = torch.random.get_rng_state()
    random_torch_state = random_states_torch[method_name]
    torch.random.set_rng_state(random_torch_state.get_state())
    try:
        yield
    finally:
        current_np_state = np.random.RandomState()
        current_np_state.set_state(np.random.get_state())

        current_torch_state = torch.manual_seed(torch.initial_seed())
        torch.random.set_rng_state(current_torch_state.get_state())

        set_model_random_state(current_np_state, current_torch_state, method_name)

        np.random.set_state(original_np_state)
        torch.random.set_rng_state(original_torch_state)


def random_state(function):
    """Set the random state before calling the function.
    Args:
        function (Callable):
            The function to wrap around.
    """
    @wraps(function)
    def wrapper(self, *args, **kwargs):
        if self.random_states is None:
            return function(self, *args, **kwargs)

        method_name = function.__name__
        with set_random_states(self.random_states, self.random_states_torch, method_name, self.set_random_state):
            return function(self, *args, **kwargs)

    return wrapper


class BaseTransformer:
    """Base class for all transformers.
    The ``BaseTransformer`` class contains methods that must be implemented
    in order to create a new transformer. The ``_fit`` method is optional,
    and ``fit_transform`` method is already implemented.
    """

    INPUT_SDTYPE = None
    SUPPORTED_SDTYPES = None
    IS_GENERATOR = None
    INITIAL_FIT_STATE = np.random.RandomState(seed=21)
    INITIAL_TRANSFORM_STATE = np.random.RandomState(seed=80)
    INITIAL_REVERSE_TRANSFORM_STATE = np.random.RandomState(seed=130)
    INITIAL_FIT_STATE_TORCH = torch.manual_seed(21)
    INITIAL_TRANSFORM_STATE_TORCH = torch.manual_seed(80)
    INITIAL_REVERSE_TRANSFORM_STATE_TORCH = torch.manual_seed(131)

    columns = None
    column_prefix = None
    output_columns = None
    missing_value_replacement = None

    def __init__(self):
        self.output_properties = {None: {'sdtype': 'float', 'next_transformer': None}}
        # self.random_states = {
        #     'fit': self.INITIAL_FIT_STATE,
        #     'transform': self.INITIAL_TRANSFORM_STATE,
        #     'reverse_transform': self.INITIAL_REVERSE_TRANSFORM_STATE, 
        # }
        # self.random_states_torch = {
        #     'fit': self.INITIAL_FIT_STATE_TORCH,
        #     'transform': self.INITIAL_TRANSFORM_STATE_TORCH,
        #     'reverse_transform': self.INITIAL_REVERSE_TRANSFORM_STATE_TORCH, 
        # }
        # Adding manual states due to pickling error with torch.manual_seed
        self.random_states = None

    def set_random_state(self, state, state_torch, method_name):
        """Set the random state for a transformer.
        Args:
            state (numpy.random.RandomState):
                The numpy random state to set.
            method_name (str):
                The method to set it for.
        """
        if method_name not in self.random_states:
            raise ValueError(
                "'method_name' must be one of 'fit', 'transform' or 'reverse_transform'."
            )
        self.random_states[method_name] = state
        self.random_states_torch[method_name] = state_torch


    def reset_randomization(self):
        """Reset the random state for ``reverse_transform``."""
        self.set_random_state(self.INITIAL_FIT_STATE, self.INITIAL_FIT_STATE_TORCH,  'fit')
        self.set_random_state(self.INITIAL_TRANSFORM_STATE, self.INITIAL_TRANSFORM_STATE_TORCH, 'transform')
        self.set_random_state(self.INITIAL_REVERSE_TRANSFORM_STATE, self.INITIAL_REVERSE_TRANSFORM_STATE_TORCH,'reverse_transform')


    def _set_missing_value_replacement(self, default, missing_value_replacement):
        if missing_value_replacement is None:
            warnings.warn(
                "Setting 'missing_value_replacement' to 'None' is no longer supported. "
                f"Imputing with the '{default}' instead.", FutureWarning
            )
            self.missing_value_replacement = default
        else:
            self.missing_value_replacement = missing_value_replacement

    @classmethod
    def get_name(cls):
        """Return transformer name.
        Returns:
            str:
                Transformer name.
        """
        return cls.__name__

    @classmethod
    def get_subclasses(cls):
        """Recursively find subclasses of this Baseline.
        Returns:
            list:
                List of all subclasses of this class.
        """
        subclasses = []
        for subclass in cls.__subclasses__():
            if abc.ABC not in subclass.__bases__:
                subclasses.append(subclass)

            subclasses += subclass.get_subclasses()

        return subclasses

    @classmethod
    def get_input_sdtype(cls):
        """Return the input sdtype supported by the transformer.
        Returns:
            string:
                Accepted input sdtype of the transformer.
        """
        return cls.INPUT_SDTYPE

    @classmethod
    def get_supported_sdtypes(cls):
        """Return the supported sdtypes by the transformer.
        Returns:
            list:
                Accepted input sdtypes of the transformer.
        """
        return cls.SUPPORTED_SDTYPES or [cls.INPUT_SDTYPE]

    def _get_output_to_property(self, property_):
        output = {}
        for output_column, properties in self.output_properties.items():
            # if 'sdtype' is not in the dict, ignore the column
            if property_ not in properties:
                continue
            if output_column is None:
                output[f'{self.column_prefix}'] = properties[property_]
            else:
                output[f'{self.column_prefix}.{output_column}'] = properties[property_]

        return output

    def get_output_sdtypes(self):
        """Return the output sdtypes produced by this transformer.
        Returns:
            dict:
                Mapping from the transformed column names to the produced sdtypes.
        """
        return self._get_output_to_property('sdtype')

    def get_next_transformers(self):
        """Return the suggested next transformer to be used for each column.
        Returns:
            dict:
                Mapping from transformed column names to the transformers to apply to each column.
        """
        return self._get_output_to_property('next_transformer')

    def is_generator(self):
        """Return whether this transformer generates new data or not.
        Returns:
            bool:
                Whether this transformer generates new data or not.
        """
        return bool(self.IS_GENERATOR)

    def get_input_column(self):
        """Return input column name for transformer.
        Returns:
            str:
                Input column name.
        """
        return self.columns[0]

    def get_output_columns(self):
        """Return list of column names created in ``transform``.
        Returns:
            list:
                Names of columns created during ``transform``.
        """
        return list(self._get_output_to_property('sdtype'))

    def _store_columns(self, columns, data):
        if isinstance(columns, tuple) and columns not in data:
            columns = list(columns)
        elif not isinstance(columns, list):
            columns = [columns]

        missing = set(columns) - set(data.columns)
        if missing:
            raise KeyError(f'Columns {missing} were not present in the data.')

        self.columns = columns

    @staticmethod
    def _get_columns_data(data, columns):
        if len(columns) == 1:
            columns = columns[0]

        return data[columns].copy()

    @staticmethod
    def _add_columns_to_data(data, transformed_data, transformed_names):
        """Add new columns to a ``pandas.DataFrame``.
        Args:
            - data (pd.DataFrame):
                The ``pandas.DataFrame`` to which the new columns have to be added.
            - transformed_data (pd.DataFrame, pd.Series, np.ndarray):
                The data of the new columns to be added.
            - transformed_names (list, np.ndarray):
                The names of the new columns to be added.
        Returns:
            ``pandas.DataFrame`` with the new columns added.
        """
        if isinstance(transformed_data, (pd.Series, np.ndarray)):
            transformed_data = pd.DataFrame(transformed_data, columns=transformed_names)

        if transformed_names:
            # When '#' is added to the column_prefix of a transformer
            # the columns of transformed_data and transformed_names don't match
            transformed_data.columns = transformed_names
            data = pd.concat([data, transformed_data.set_index(data.index)], axis=1)

        return data

    def _build_output_columns(self, data):
        self.column_prefix = '#'.join(self.columns)
        self.output_columns = self.get_output_columns()

        # make sure none of the generated `output_columns` exists in the data,
        # except when a column generates another with the same name
        output_columns = set(self.output_columns) - set(self.columns)
        repeated_columns = set(output_columns) & set(data.columns)
        while repeated_columns:
            warnings.warn(
                f'The output columns {repeated_columns} generated by the {self.get_name()} '
                'transformer already exist in the data (or they have already been generated '
                "by some other transformer). Appending a '#' to the column name to distinguish "
                'between them.'
            )
            self.column_prefix += '#'
            self.output_columns = self.get_output_columns()
            output_columns = set(self.output_columns) - set(self.columns)
            repeated_columns = set(output_columns) & set(data.columns)

    def __repr__(self):
        """Represent initialization of transformer as text.
        Returns:
            str:
                The name of the transformer followed by any non-default parameters.
        """
        class_name = self.__class__.get_name()
        custom_args = []
        args = inspect.getfullargspec(self.__init__)
        keys = args.args[1:]
        defaults = args.defaults or []
        defaults = dict(zip(keys, defaults))
        instanced = {key: getattr(self, key) for key in keys}

        if defaults == instanced:
            return f'{class_name}()'

        for arg, value in instanced.items():
            if defaults[arg] != value:
                custom_args.append(f'{arg}={repr(value)}')

        args_string = ', '.join(custom_args)
        return f'{class_name}({args_string})'

    def _fit(self, columns_data):
        """Fit the transformer to the data.
        Args:
            columns_data (pandas.DataFrame or pandas.Series):
                Data to transform.
        """
        raise NotImplementedError()

    @random_state
    def fit(self, data, column):
        """Fit the transformer to a ``column`` of the ``data``.
        Args:
            data (pandas.DataFrame):
                The entire table.
            column (str):
                Column name. Must be present in the data.
        """
        self._store_columns(column, data)
        columns_data = self._get_columns_data(data, self.columns)
        self._fit(columns_data)
        self._build_output_columns(data)

    def _transform(self, columns_data, probs=None, column_name=None):
        """Transform the data.
        Args:
            columns_data (pandas.DataFrame or pandas.Series):
                Data to transform.
        Returns:
            pandas.DataFrame or pandas.Series:
                Transformed data.
        """
        raise NotImplementedError()




    @random_state
    def transform(self, data, probs=None, column_name=None):
        """Transform the `self.columns` of the `data`.
        Args:
            data (pandas.DataFrame):
                The entire table.
        Returns:
            pd.DataFrame:
                The entire table, containing the transformed data.
        """

        data = self._transform(data, probs, column_name)

        return data

    def fit_transform(self, data, column):
        """Fit the transformer to a `column` of the `data` and then transform it.
        Args:
            data (pandas.DataFrame):
                The entire table.
            column (str):
                A column name.
        Returns:
            pd.DataFrame:
                The entire table, containing the transformed data.
        """
        self.fit(data, column)
        return self.transform(data)

    def _reverse_transform(self, columns_data):
        """Revert the transformations to the original values.
        Args:
            columns_data (pandas.DataFrame or pandas.Series):
                Data to revert.
        Returns:
            pandas.DataFrame or pandas.Series:
                Reverted data.
        """
        raise NotImplementedError()



    @random_state
    def reverse_transform(self, data):
        """Revert the transformations to the original values.
        Args:
            data (pandas.DataFrame):
                The entire table.
        Returns:
            pandas.DataFrame:
                The entire table, containing the reverted data.
        """
        # if `data` doesn't have the columns that were transformed, don't reverse_transform
        data = self._reverse_transform(data)
        return data