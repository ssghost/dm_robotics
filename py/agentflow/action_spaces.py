# Copyright 2020 DeepMind Technologies Limited.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""ActionSpace implementations."""

import re
from typing import List, Optional, Sequence, Tuple, Union

from absl import logging
from dm_env import specs
from dm_robotics.agentflow import core
from dm_robotics.agentflow import spec_utils
import numpy as np

# Internal profiling


class _Deslicer(core.ActionSpace):
  """Creates a value by projecting the given value into a larger one."""

  def __init__(
      self,
      name: str,
      spec: core.Spec,
      output_shape: Tuple[int],  # 1-d
      output_dtype: np.dtype,
      mask: Sequence[bool],
      default_value: Optional[np.floating] = None):
    super(_Deslicer, self).__init__()
    self._name = name
    self._input_spec = spec
    self._output_shape = output_shape
    self._output_dtype = output_dtype
    self._mask = mask
    if not np.any(mask):
      logging.warning('Deslicer passed a mask with no valid indices to write'
                      'to.')
    self._default = np.nan if default_value is None else default_value

  @property
  def name(self) -> str:
    return self._name

  def spec(self) -> core.Spec:
    return self._input_spec

  # Profiling for .wrap('Deslicer.project')
  def project(self, action: np.ndarray) -> np.ndarray:
    output = np.full(
        shape=self._output_shape,
        fill_value=self._default,
        dtype=self._output_dtype)
    if np.any(self._mask):
      output[self._mask] = action
    return output


def prefix_slicer(
    spec: core.Spec,
    prefix: str,
    default_value: Optional[float] = None) -> core.ActionSpace[core.Spec]:
  """An ActionSpace for actions starting with prefix.

  The spec name is split on tab, and it's expected that the number of names
  from this split matches the shape of the spec, I.e. that each component has
  a name.
  The returned ActionSpace will project from actions with the prefix to the
  given spec, inserting default_value (or NaN, if missing).
  I.e, given a spec with seven components that start with 'robot_0' and
  some that do not, this function will return an ActionSpace of size seven
  that when projected will have the same size as the input spec did, but with
  NaNs for all the components that don't start with 'robot_0'.

  Args:
    spec: The (primitive) action spec to 'slice'.
    prefix: A regular expression for components to select. Note that we use
      regular expression comparison, so you can use exclusion patterns too.
    default_value: The default value used by the Desclicer.

  Returns:
    An ActionSpace.
      Given a value that conforms to the (currently implicit) input spec,
      return a value that conforms to the larger spec given to this function.

  Raises:
    ValueError: If a non-primitive spec is given or the names in the spec don't
      split as expected.
  """
  # Special case an empty input spec.
  if np.prod(spec.shape) == 0:
    return core.IdentityActionSpace(spec)

  names = np.asarray(spec.name.split('\t'))
  prefix_expr = re.compile(prefix)
  indices: List[bool] = [
      re.match(prefix_expr, name) is not None for name in names
  ]

  if len(names) != spec.shape[0]:
    raise ValueError('Expected {} names, got {}.  Name: {}'.format(
        spec.shape[0], len(names), names))

  if isinstance(spec, specs.DiscreteArray):
    raise ValueError('Support for DiscreteArray not implemented, yet.')
  elif isinstance(spec, specs.BoundedArray):
    input_spec = specs.BoundedArray(
        shape=(np.count_nonzero(indices),),
        dtype=spec.dtype,
        minimum=spec.minimum[indices],
        maximum=spec.maximum[indices],
        name='\t'.join(names[indices]))
  elif isinstance(spec, specs.Array):
    input_spec = specs.Array(
        shape=(np.count_nonzero(indices),),
        dtype=spec.dtype,
        name='\t'.join(names[indices]))
  else:
    raise ValueError('unknown spec type: {}'.format(type(spec)))

  return _Deslicer(
      name=prefix,
      spec=input_spec,
      output_shape=spec.shape,
      output_dtype=spec.dtype,
      mask=indices,
      default_value=default_value)


class CastActionSpace(core.ActionSpace):
  """Casts actions to the appropriate dtype for the provided spec."""

  def __init__(self,
               spec: core.Spec,
               ignore_nan: Optional[bool] = None,
               name: str = 'cast'):
    """Initializes SequentialActionSpace.

    Note: ShrinkToFitActionSpace also casts, so this should only be used if
    scaling is not desired.

    Args:
      spec: Specification for value to cast to.
      ignore_nan: If True, NaN values will not fail validation. If None, this is
        determined by the shape of `value`, so that large arrays (e.g. images)
        are not checked  (for performance reasons).
      name: A name for action space.
    """
    if np.issubdtype(spec.dtype, np.integer):
      logging.warning('Casting to %s will fail for NaN', spec.dtype)

    self._spec = spec
    self._ignore_nan = ignore_nan
    self._name = name

  @property
  def name(self) -> str:
    return self._name

  def spec(self) -> core.Spec:
    return self._spec

  def project(self, action: np.ndarray) -> np.ndarray:
    cast_action = action.astype(self._spec.dtype)
    spec_utils.validate(self._spec, cast_action, self._ignore_nan)
    return cast_action


class ShrinkToFitActionSpace(core.ActionSpace[specs.BoundedArray]):
  """Action space that scales an action if any component falls out of bounds."""

  def __init__(self,
               spec: specs.BoundedArray,
               ignore_nan: Optional[bool] = None,
               name: str = 'shrink_to_fit'):
    """Action space that scales the value towards zero to fit within spec.

    This action-space also casts the value to the dtype of the provided spec.

    Args:
      spec: Specification for value to scale and clip.
      ignore_nan: If True, NaN values will not fail validation. If None, this is
        determined by the shape of `value`, so that large arrays (e.g. images)
        are not checked  (for performance reasons).
      name: A name for action space.
    """
    self._spec = spec
    self._ignore_nan = ignore_nan
    self._name = name

  @property
  def name(self) -> str:
    return self._name

  def spec(self) -> specs.BoundedArray:
    return self._spec

  def project(self, action: np.ndarray) -> np.ndarray:
    return spec_utils.shrink_to_fit(
        value=action, spec=self._spec, ignore_nan=self._ignore_nan)


class FixedActionSpace(core.ActionSpace):
  """Like a partial function application, for an action space."""

  def __init__(self, action_space: core.ActionSpace, fixed_value: np.ndarray):
    self._action_space = action_space
    self._fixed_value = fixed_value
    space_shape = action_space.spec().shape
    value_shape = fixed_value.shape
    if space_shape != value_shape:
      raise ValueError('Shape mismatch. Spec: {} ({}), Value: {} ({})'.format(
          action_space, space_shape, fixed_value, value_shape))

  @property
  def name(self) -> str:
    return 'Fixed'

  def spec(self) -> core.Spec:
    return specs.BoundedArray((0,), np.float32, minimum=[], maximum=[], name='')

  def project(self, action: np.ndarray) -> np.ndarray:
    return self._action_space.project(self._fixed_value)


class SequentialActionSpace(core.ActionSpace):
  """Apply a sequence of ActionSpaces iteratively.

  This allows users to compose action transformations, or apply a transformation
  to a subset of a larger action space, e.g. one sliced out by `prefix_slicer`.
  """

  def __init__(self,
               action_spaces: Sequence[core.ActionSpace[core.Spec]],
               name: Optional[str] = None):
    """Initialize SequentialActionSpace.

    Args:
      action_spaces: A sequence of action spaces to apply in order.
      name: Optional name. Defaults to 0th action space name.
    """
    self._action_spaces = action_spaces
    self._name = name or action_spaces[0].name

  @property
  def name(self) -> str:
    return self._name

  def spec(self) -> core.Spec:
    return self._action_spaces[0].spec()

  def project(self, action: np.ndarray) -> np.ndarray:
    """Projects the action iteratively through the sequence."""
    for action_space in self._action_spaces:
      action = action_space.project(action)
    return action


def constrained_action_spec(minimum: Union[float, Sequence[float]],
                            maximum: Union[float, Sequence[float]],
                            base: specs.BoundedArray) -> specs.BoundedArray:
  """Returns action spec bounds constrained by the given minimum and maximum.

  Args:
    minimum: The new minimum spec constraint.
    maximum: The new maximum spec constraint.
    base: The base action space spec.
  """

  minimum = np.array(minimum, dtype=base.dtype)
  if minimum.shape != base.minimum.shape:
    raise ValueError('minimum not compatible with base shape')
  minimum = np.maximum(base.minimum, minimum)

  maximum = np.array(maximum, dtype=base.dtype)
  if maximum.shape != base.maximum.shape:
    raise ValueError('maximum not compatible with base shape')
  maximum = np.minimum(base.maximum, maximum)

  # Check that mins and maxs are non intersecting.
  if np.any(minimum > maximum):
    raise ValueError('minimum and maximum bounds intersect')

  return specs.BoundedArray(
      shape=base.shape,
      dtype=base.dtype,
      minimum=minimum,
      maximum=maximum,
      name=base.name)


def constrained_action_space(
    minimum: Union[float, Sequence[float]],
    maximum: Union[float, Sequence[float]],
    base: core.ActionSpace[specs.BoundedArray],
    name: Optional[str] = None) -> core.ActionSpace[specs.BoundedArray]:
  """Returns an action space that is a constrained version of the base space."""

  spec = constrained_action_spec(minimum, maximum, base.spec())
  constrained_space = core.IdentityActionSpace(spec)
  return SequentialActionSpace([constrained_space, base], name)
