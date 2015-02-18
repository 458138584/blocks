"""Defines models.

A model is a thin layer of abstraction between the user-defined computation
graph, bricks, parameters and main loop extensions. This module provides
the basic :class:`AbstractModel` interface as well as its implementations
(currently only :class:`Model`).

"""
import logging
from abc import ABCMeta, abstractmethod
from collections import OrderedDict
from itertools import chain

from six import add_metaclass

from blocks.graph import ComputationGraph
from blocks.select import Selector
from blocks.filter import VariableFilter, get_brick
from blocks.roles import PARAMETER

logger = logging.getLogger()


@add_metaclass(ABCMeta)
class AbstractModel(object):
    """A parameterized entity trained in the main loop.

    A model is a parameterized entity the user trains a in a main loop.
    The following are traits of every model:

    * It has parameters and supports a way to access them. In addition
    to returning handles to parameter objects it can return their values
    as numpy arrays and set their values to given numpy arrays.

    * It has an optimality objective.

    * It can be serialized and deserialized by mean of pickling.

    * It might have bricks as its components.

    This class provides an interface for models. For experiments use
    a subclass, e.g. the :class:`Model`.

    """
    @abstractmethod
    def get_params(self):
        """Return the model parameters.

        Returns
        -------
        params : OrderedDict
            Dictionary of (name, parameter) pairs.

        """
        pass

    def get_param_values(self):
        """Return the values of model parameters.

        The default implementation assumes that parameters are Theano
        shared variables.

        Returns
        -------
        param_values : OrderedDict
            Dictionary of (parameter name, :class:`~numpy.ndarray`) pairs.

        """
        return OrderedDict((name, param.get_value())
                           for name, param in self.get_params().items())

    def set_param_values(self, param_values):
        """Set the values of model parameters.

        The default implementation assumes that parameters are Theano
        shared variables.

        Parameters
        ----------
        param_values : OrderedDict
            Dictionary of (parameter name, :class:`~numpy.ndarray`) pairs.

        """
        params = self.get_params()

        unknown = set(param_values) - set(params)
        missing = set(params) - set(param_values)
        if len(unknown):
            logger.error("unknown parameter names: {}\n".format(unknown))
        if len(missing):
            logger.error("missing values for parameters: {}\n".format(missing))

        for name, value in param_values.items():
            if name in params:
                params[name].set_value(value)

    @abstractmethod
    def get_objective(self):
        """Return the optimization objective."""
        pass

    def get_top_bricks(self):
        """Return the top-level bricks that are used in the model.

        Returns
        -------
        bricks : list
            List of bricks.

        """
        raise NotImplementedError()


class Model(AbstractModel, ComputationGraph):
    """Wraps a computation graph to support model interface.

    This model covers the most common case when all information
    about the model is contained in an annotated computation graph:
    parameters are identified by the roles, bricks found by annotations.
    Due to frequency of this case this class is called simply 'Model'
    and not 'ComputationGraphModel'.

    Parameters
    ----------
    outputs : (list of) :class:`~theano.Variable`
        The output variables of the computation graph.

    .. todo::

        Overriding the automatically found parameters and bricks might
        be needed.

        If there top bricks in scan inner graphs, those will not be found.

    """
    def __init__(self, outputs):
        super(Model, self).__init__(outputs)

        bricks = [get_brick(var) for var in self if get_brick(var)]
        children = set(chain(*(brick.children for brick in bricks)))
        # Quadratic complexity: we should not have thousands of
        # top-level bricks.
        self.top_bricks = []
        for brick in bricks:
            if brick not in children and brick not in self.top_bricks:
                self.top_bricks.append(brick)
        if len(set(b.name for b in self.top_bricks)) < len(self.top_bricks):
            raise ValueError("top bricks with the same name")

        brick_param_names = {
            v: k for k, v in Selector(self.top_bricks).get_params().items()}
        self.params = []
        for param in VariableFilter(roles=[PARAMETER])(self.shared_variables):
            if param in brick_param_names:
                self.params.append((brick_param_names[param], param))
            else:
                self.params.append((param.name, param))
        self.params = OrderedDict(self.params)

    def get_objective(self):
        """Return the output variable, if there is a single one.

        If there is only one output variable, it is a reasonable default
        setting to assume that it is the optimization objective.

        """
        if len(self.outputs) == 1:
            return self.outputs[0]
        raise NotImplementedError

    def get_params(self):
        """Get model parameters.

        The parameter names are formed from positions of their owner bricks
        in the bricks hierarchy. The variable names are used for the
        parameters that do not belong to any brick.

        """
        return self.params

    def get_top_bricks(self):
        return self.top_bricks
