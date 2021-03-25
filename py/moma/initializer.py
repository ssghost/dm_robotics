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

"""Base class for MOMA initializers that return a boolean indicating success."""

import abc
from typing import Any
from dm_control import composer


class Initializer(composer.Initializer):
  """Composer initializer that returns whether it was successful."""

  @abc.abstractmethod
  def __call__(self, physics: Any, random_state: Any) -> bool:
    raise NotImplementedError

  def reset(self, physics: Any) -> bool:
    """Resets this initializer. Returns true if successful."""
    return True
