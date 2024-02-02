# Copyright 2020 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""SVD algorithm, where the training and inference graphs are different."""
from typing import List

import tensorflow as tf

from tensorflow_model_optimization.python.core.common.keras.compression import algorithm
from tensorflow_model_optimization.python.core.keras.compat import keras


class SVD(algorithm.WeightCompressor):
  """Define how to apply SVD algorithm."""

  def __init__(self, rank):
    self.rank = rank

  # TODO(tfmot): communicate that `pretrained_weight` will sometimes
  # be a dummy tensor and sometimes be actual pretrained values during
  # its actual usage.
  def init_training_weights(
      self, pretrained_weight: tf.Tensor):
    self.add_training_weight(
        name='w',
        shape=pretrained_weight.shape,
        dtype=pretrained_weight.dtype,
        initializer=keras.initializers.Constant(pretrained_weight),
    )

  def decompress_weights(self, u: tf.Tensor, sv: tf.Tensor) -> tf.Tensor:
    return tf.matmul(u, sv)

  def compress_training_weights(self, weight: tf.Tensor) -> List[tf.Tensor]:
    rank = self.rank
    s, u, v = tf.linalg.svd(weight)

    if len(weight.shape) == 2:
      # FC Layer
      s = s[:rank]
      u = u[:, :rank]
      v = v[:, :rank]
    elif len(weight.shape) == 4:
      # Conv2D Layer
      s = s[:, :, :rank]
      u = u[:, :, :, :rank]
      v = v[:, :, :, :rank]
    else:
      raise NotImplementedError('Only for dimension=2 or 4 is supported.')

    sv = tf.matmul(tf.linalg.diag(s), v, adjoint_b=True)

    return [u, sv]

  # TODO(tfmot): remove in this example, which is just post-training.
  def project_training_weights(self, weight: tf.Tensor) -> tf.Tensor:
    return weight

  def get_compressible_weights(
      self, original_layer: keras.layers.Layer
  ) -> List[str]:
    if isinstance(original_layer, keras.layers.Conv2D) or isinstance(
        original_layer, keras.layers.Dense
    ):
      return [original_layer.kernel]
    return []

  # TODO(tfmot): consider if we can simplify `create_model_for_training` and
  # `create_model_for_inference` into a single API for algorithm developers.
  def compress_model(self, to_optimize: keras.Model) -> keras.Model:
    """Model developer API for optimizing a model."""
    # pylint: disable=protected-access
    if (
        not isinstance(to_optimize, keras.Sequential)
        and not to_optimize._is_graph_network
    ):
      raise ValueError(
          '`compress_model` can only either be a keras Sequential or '
          'Functional model.'
      )
    # pylint: enable=protected-access

    def _create_layer_for_training(layer):
      # Require layer to be built so that the SVD-factorized weights
      # can be initialized from the weights.
      if not layer.built:
        raise ValueError(
            'Applying SVD currently requires passing in a built model')

      return algorithm.create_layer_for_training(layer, algorithm=self)

    def _create_layer_for_inference(layer):
      return algorithm.create_layer_for_inference(layer, algorithm=self)

    intermediate_model = keras.models.clone_model(
        to_optimize, clone_function=_create_layer_for_training
    )

    return keras.models.clone_model(
        intermediate_model, clone_function=_create_layer_for_inference
    )
