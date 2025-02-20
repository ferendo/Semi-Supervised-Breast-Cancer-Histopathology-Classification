# This implementation is based on the DenseNet-BC implementation in torchvision
# https://github.com/pytorch/vision/blob/master/torchvision/models/densenet.py

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.checkpoint as cp
from collections import OrderedDict
from cbam import CBAM

# TODO: Delete if we do not use memory efficient version
def _bn_function_factory(norm, leaky_relu, conv):
    def bn_function(*inputs):
        concated_features = torch.cat(inputs, 1)
        bottleneck_output = conv(leaky_relu(norm(concated_features)))
        return bottleneck_output

    return bn_function


class DenseLayer(nn.Module):
    def __init__(self, input_shape, growth_rate, bottleneck_factor, drop_rate, efficient=False,
                 use_bias=True, dilation=1):
        super(DenseLayer, self).__init__()
        self.drop_rate = drop_rate
        self.efficient = efficient
        self.use_bias = use_bias
        self.growth_rate = growth_rate
        self.input_shape = input_shape
        self.layer_dict = nn.ModuleDict()
        self.bottleneck_factor = bottleneck_factor # bottleneck size
        self.dilation = dilation
        self.padding = self.dilation

        # build the network
        self.build_module()

    def build_module(self):
        # Assuming input shape is the pre-concatenated tensor shape
        # num_input_features should be dim 1 of the 4d tensor
        print('Dense Layer shape', self.input_shape)
        x = torch.zeros(self.input_shape)
        out = x

        self.layer_dict['bn_1'] = nn.BatchNorm2d(out.shape[1])
        out = self.layer_dict['bn_1'].forward(out)
        out = F.leaky_relu(out)

        self.layer_dict['conv_1'] = nn.Conv2d(in_channels=out.shape[1],
                                              out_channels=self.bottleneck_factor * self.growth_rate,
                                              kernel_size=1, stride=1, bias=self.use_bias)
        out = self.layer_dict['conv_1'].forward(out)

        self.layer_dict['bn_2'] = nn.BatchNorm2d(out.shape[1])
        out = self.layer_dict['bn_2'].forward(out)
        out = F.leaky_relu(out)

        self.layer_dict['conv_2'] = nn.Conv2d(in_channels=out.shape[1],
                                              out_channels=self.growth_rate,
                                              kernel_size=3,
                                              stride=1,
                                              padding=self.padding,
                                              bias=self.use_bias,
                                              dilation=self.dilation)
        out = self.layer_dict['conv_2'].forward(out)

        # TODO: Checkout dropout 2d
        if self.drop_rate > 0:
            print('Dropout with', self.drop_rate)
            self.layer_dict['dropout'] = nn.Dropout(p=self.drop_rate)
            out = self.layer_dict['dropout'](out)

        return out

    def forward(self, *prev_features):
        # concatenated features
        out = torch.cat(prev_features, 1)
        out = self.layer_dict['bn_1'].forward(out)
        out = F.leaky_relu(out)
        out = self.layer_dict['conv_1'].forward(out)

        out = self.layer_dict['bn_2'].forward(out)
        out = F.leaky_relu(out)
        out = self.layer_dict['conv_2'].forward(out)

        if self.drop_rate > 0:
            out = self.layer_dict['dropout'](out)

        return out

    def forward_original(self, *prev_features):
        bn_function = _bn_function_factory(self.norm1, self.leaky_relu1, self.conv1)
        if self.efficient and any(prev_feature.requires_grad for prev_feature in prev_features):
            bottleneck_output = cp.checkpoint(bn_function, *prev_features)
        else:
            bottleneck_output = bn_function(*prev_features)
        new_features = self.conv2(self.leaky_relu2(self.norm2(bottleneck_output)))
        if self.drop_rate > 0:
            new_features = F.dropout(new_features, p=self.drop_rate, training=self.training)
        return new_features

    def reset_parameters(self):
        """
        Re-initialize the network parameters.
        """
        for item in self.layer_dict.children():
            try:
                item.reset_parameters()
            except:
                pass


class DenseSeLayer(nn.Module):
    def __init__(self, input_shape, growth_rate, bottleneck_factor, drop_rate, efficient=False,
                 use_bias=True, use_se=False, se_reduction=16, dilation=1):
        super(DenseSeLayer, self).__init__()
        self.drop_rate = drop_rate
        self.efficient = efficient
        self.use_bias = use_bias
        self.growth_rate = growth_rate
        self.input_shape = input_shape
        self.layer_dict = nn.ModuleDict()
        self.bottleneck_factor = bottleneck_factor # bottleneck size
        self.se_reduction = se_reduction
        self.dilation = dilation
        self.padding = self.dilation

        # build the network
        self.build_module()

    def build_module(self):
        # Assuming input shape is the pre-concatenated tensor shape
        # num_input_features should be dim 1 of the 4d tensor
        print('Dense Layer shape', self.input_shape)
        x = torch.zeros(self.input_shape)
        out = x
        #
        # self.layer_dict['se'] = SqueezeExciteLayer(input_shape=out.shape,
        #                                            reduction=self.se_reduction,
        #                                            use_bias=False)
        self.layer_dict['se'] = CBAM(out.shape[1], self.se_reduction)
        out = self.layer_dict['se'].forward(out)

        self.layer_dict['bn_1'] = nn.BatchNorm2d(out.shape[1])
        out = self.layer_dict['bn_1'].forward(out)
        out = F.leaky_relu(out)

        self.layer_dict['conv_1'] = nn.Conv2d(in_channels=out.shape[1],
                                              out_channels=self.bottleneck_factor * self.growth_rate,
                                              kernel_size=1, stride=1, bias=self.use_bias)
        out = self.layer_dict['conv_1'].forward(out)

        self.layer_dict['bn_2'] = nn.BatchNorm2d(out.shape[1])
        out = self.layer_dict['bn_2'].forward(out)
        out = F.leaky_relu(out)

        self.layer_dict['conv_2'] = nn.Conv2d(in_channels=out.shape[1],
                                              out_channels=self.growth_rate,
                                              kernel_size=3, stride=1, padding=self.dilation, bias=self.use_bias,
                                              dilation=self.dilation)
        out = self.layer_dict['conv_2'].forward(out)

        # TODO: Checkout dropout 2d
        if self.drop_rate > 0:
            print('Dropout with', self.drop_rate)
            self.layer_dict['dropout'] = nn.Dropout(p=self.drop_rate)
            out = self.layer_dict['dropout'](out)

        return out

    def forward(self, *prev_features):
        # concatenated features
        out = torch.cat(prev_features, 1)

        out = self.layer_dict['se'].forward(out)

        out = self.layer_dict['bn_1'].forward(out)
        out = F.leaky_relu(out)
        out = self.layer_dict['conv_1'].forward(out)

        out = self.layer_dict['bn_2'].forward(out)
        out = F.leaky_relu(out)
        out = self.layer_dict['conv_2'].forward(out)

        if self.drop_rate > 0:
            out = self.layer_dict['dropout'](out)

        return out

    def forward_original(self, *prev_features):
        bn_function = _bn_function_factory(self.norm1, self.leaky_relu1, self.conv1)
        if self.efficient and any(prev_feature.requires_grad for prev_feature in prev_features):
            bottleneck_output = cp.checkpoint(bn_function, *prev_features)
        else:
            bottleneck_output = bn_function(*prev_features)
        new_features = self.conv2(self.leaky_relu2(self.norm2(bottleneck_output)))
        if self.drop_rate > 0:
            new_features = F.dropout(new_features, p=self.drop_rate, training=self.training)
        return new_features

    def reset_parameters(self):
        """
        Re-initialize the network parameters.
        """
        for item in self.layer_dict.children():
            try:
                item.reset_parameters()
            except:
                pass


# TODO: Turn this into mlp style
class Transition(nn.Sequential):
    def __init__(self, input_shape, num_output_filters, use_bias):
        super(Transition, self).__init__()

        self.input_shape = input_shape
        self.num_output_filters = num_output_filters
        self.use_bias = use_bias
        self.layer_dict = nn.ModuleDict()

        # build the network
        self.build_module()

    def build_module(self):
        print('Transition Layer shape', self.input_shape)
        x = torch.zeros(self.input_shape)
        out = x

        self.layer_dict['bn_1'] = nn.BatchNorm2d(out.shape[1])
        out = self.layer_dict['bn_1'].forward(out)
        out = F.leaky_relu(out)

        self.layer_dict['conv_1'] = nn.Conv2d(in_channels=out.shape[1], out_channels=self.num_output_filters,
                                              kernel_size=1, stride=1, bias=self.use_bias)
        out = self.layer_dict['conv_1'].forward(out)

        self.layer_dict['pool_1'] = nn.AvgPool2d(kernel_size=2, stride=2)
        out = self.layer_dict['pool_1'].forward(out)

        return out

    def forward(self, inputs):
        out = self.layer_dict['bn_1'].forward(inputs)
        out = F.leaky_relu(out)
        out = self.layer_dict['conv_1'].forward(out)

        out = self.layer_dict['pool_1'].forward(out)

        return out

    def reset_parameters(self):
        """
        Re-initialize the network parameters.
        """
        for item in self.layer_dict.children():
            try:
                item.reset_parameters()
            except:
                pass


class DenseBlock(nn.Module):
    def __init__(self, input_shape, num_layers, bottleneck_factor, growth_rate, drop_rate, efficient=False,
                 use_bias=True, use_se=False, se_reduction=16, increasing_dilation=False):
        super(DenseBlock, self).__init__()

        self.drop_rate = drop_rate
        self.efficient = efficient
        self.use_bias = use_bias
        self.growth_rate = growth_rate
        self.input_shape = input_shape
        self.layer_dict = nn.ModuleDict()
        # Bottleneck size
        self.bottleneck_factor = bottleneck_factor
        self.num_layers = num_layers
        self.use_se = use_se
        self.se_reduction = se_reduction
        self.increasing_dilation = increasing_dilation

        # build the network
        self.build_module()

    def build_module(self):
        print('\nDense Block', self.input_shape)
        x = torch.zeros(self.input_shape)
        features = [x]

        dilation = 1

        # self.num_input_features + i * self.growth_rate,
        for i in range(self.num_layers):
            out = torch.cat(features, 1)

            if self.use_se:
                self.layer_dict['dense_se_layer_%d' % (i + 1)] = DenseSeLayer(
                    input_shape=out.shape,
                    growth_rate=self.growth_rate,
                    bottleneck_factor=self.bottleneck_factor,
                    drop_rate=self.drop_rate,
                    efficient=self.efficient,
                    use_bias=self.use_bias,
                    se_reduction=self.se_reduction,
                    dilation=dilation
                )
                out = self.layer_dict['dense_se_layer_%d' % (i + 1)].forward(*features)
            else:
                self.layer_dict['dense_layer_%d' % (i + 1)] = DenseLayer(
                    input_shape=out.shape,
                    growth_rate=self.growth_rate,
                    bottleneck_factor=self.bottleneck_factor,
                    drop_rate=self.drop_rate,
                    efficient=self.efficient,
                    use_bias=self.use_bias,
                    dilation=dilation
                )
                out = self.layer_dict['dense_layer_%d' % (i + 1)].forward(*features)
            features.append(out)

            if self.increasing_dilation:
                dilation = dilation * 2

        feature_tensor = torch.cat(features, 1)

        # if self.use_se:
        #     self.layer_dict['se'] = self.layer_dict['se'] = SqueezeExciteLayer(input_shape=feature_tensor.shape,
        #                                            reduction=self.se_reduction,
        #                                            use_bias=False)
        #     feature_tensor = self.layer_dict['se'].forward(feature_tensor)

        return feature_tensor

    def forward(self, init_features):
        features = [init_features]

        for name, layer in self.layer_dict.items():
            new_features = layer.forward(*features)
            features.append(new_features)

        feature_tensor = torch.cat(features, 1)

        # if self.use_se:
        #     feature_tensor = self.layer_dict['se'].forward(feature_tensor)
        return feature_tensor

    def reset_parameters(self):
        """
        Re-initialize the network parameters.
        """
        for item in self.layer_dict.children():
            try:
                item.reset_parameters()
            except:
                pass


class DenseNet(nn.Module):
    r"""Densenet-BC model class, based on
    `"Densely Connected Convolutional Networks" <https://arxiv.org/pdf/1608.06993.pdf>`
    Args:
        growth_rate (int) - how many filters to add each layer (`k` in paper)
        block_config (list of 3 or 4 ints) - how many layers in each pooling block
        num_init_features (int) - the number of filters to learn in the first convolution layer
        bn_size (int) - multiplicative factor for number of bottle neck layers
            (i.e. bn_size * k features in the bottleneck layer)
        drop_rate (float) - dropout rate after each dense layer
        num_classes (int) - number of classification classes
        small_inputs (bool) - set to True if images are 32x32. Otherwise assumes images are larger.
        efficient (bool) - set to True to use checkpointing. Much more memory efficient, but slower.
    """

    def __init__(self, input_shape, growth_rate=12, block_config=(6, 12, 24, 16), compression=0.5,
                 num_init_features=24, bottleneck_factor=4, drop_rate=0,
                 num_classes=10, small_inputs=True, efficient=False, use_bias=True,
                 use_se=False, se_reduction=16, increasing_dilation=False, no_classification=False):
        super(DenseNet, self).__init__()
        assert 0 < compression <= 1, 'compression of densenet should be between 0 and 1'

        self.input_shape = input_shape
        self.growth_rate = growth_rate
        self.block_config = block_config
        self.num_init_features = num_init_features
        self.bottleneck_factor = bottleneck_factor
        self.drop_rate = drop_rate
        self.num_classes = num_classes
        self.small_inputs = small_inputs
        self.efficient = efficient
        self.use_bias = use_bias
        self.layer_dict = nn.ModuleDict()
        self.compression = compression
        self.use_se = use_se
        self.se_reduction = se_reduction
        self.increasing_dilation = increasing_dilation
        self.no_classification = no_classification

        self.build_module()

    def build_module(self):
        x = torch.zeros(self.input_shape)
        out = x

        self.layer_dict['input_0'] = InputConvolutionBlock(out.shape, self.num_init_features, self.small_inputs,
                                                           self.use_bias)

        out = self.layer_dict['input_0'].forward(out)
        print('Block config:',self.block_config)
        # Each DenseBlock
        for i, num_layers in enumerate(self.block_config):
            block = DenseBlock(
                input_shape=out.shape,
                num_layers=num_layers,
                bottleneck_factor=self.bottleneck_factor,
                growth_rate=self.growth_rate,
                drop_rate=self.drop_rate,
                efficient=self.efficient,
                use_bias=self.use_bias,
                use_se=self.use_se,
                se_reduction=self.se_reduction,
                increasing_dilation=self.increasing_dilation
            )

            self.layer_dict[f"denseblock_{i + 1}"] = block
            out = self.layer_dict[f"denseblock_{i + 1}"].forward(out)

            if i != len(self.block_config) - 1:
                trans = Transition(input_shape=out.shape,
                                   num_output_filters=int(out.shape[1] * self.compression),
                                   use_bias=self.use_bias)

                self.layer_dict[f'transition_{(i + 1)}'] = trans
                out = self.layer_dict[f'transition_{(i + 1)}'].forward(out)

        self.layer_dict['final_bn'] = nn.BatchNorm2d(out.shape[1])
        out = self.layer_dict['final_bn'].forward(out)

        if not self.no_classification:
            out = F.leaky_relu(out)
            out = F.adaptive_avg_pool2d(out, (1, 1))
            out = torch.flatten(out, 1)

            self.layer_dict['final_classifier'] = nn.Linear(out.shape[1], self.num_classes)
            out = self.layer_dict['final_classifier'].forward(out)
        return out

    def forward(self, x):
        out = x
        out = self.layer_dict['input_0'].forward(out)

        for i, num_layers in enumerate(self.block_config):
            out = self.layer_dict[f"denseblock_{i + 1}"].forward(out)

            if i != len(self.block_config) - 1:
                out = self.layer_dict[f'transition_{(i + 1)}'].forward(out)

        out = self.layer_dict['final_bn'].forward(out)

        if not self.no_classification:
            out = F.leaky_relu(out)
            out = F.adaptive_avg_pool2d(out, (1, 1))
            out = torch.flatten(out, 1)

            out = self.layer_dict['final_classifier'].forward(out)

        return out

    def reset_parameters(self):
        """
        Re-initialize the network parameters.
        """
        for item in self.layer_dict.children():
            try:
                item.reset_parameters()
            except:
                pass


class InputConvolutionBlock(nn.Module):
    def __init__(self, input_shape, num_filters, small_inputs, use_bias=True):
        super(InputConvolutionBlock, self).__init__()

        self.input_shape = input_shape
        self.num_filters = num_filters
        self.use_bias = use_bias
        self.small_inputs = small_inputs
        # Initialize a module dict, which is effectively a dictionary that can collect layers and integrate
        # them into pytorch
        self.layer_dict = nn.ModuleDict()
        # build the network
        self.build_module()

    def build_module(self):
        print("Building First_Convolutional_Block in Densenet with input shape %s" % (self.input_shape,))

        x = torch.zeros(self.input_shape)
        out = x

        if self.small_inputs:
            # TODO: BatchNorm ?
            self.layer_dict['conv_0'] = nn.Conv2d(out.shape[1], self.num_filters, kernel_size=3,
                                                  stride=1, padding=1, bias=self.use_bias)
            out = self.layer_dict['conv_0'].forward(out)
        else:
            self.layer_dict['conv_0'] = nn.Conv2d(out.shape[1], self.num_filters, kernel_size=7,
                                                  stride=2, padding=3, bias=self.use_bias)
            out = self.layer_dict['conv_0'].forward(out)

            self.layer_dict['bn_0'] = nn.BatchNorm2d(out.shape[1])
            out = self.layer_dict['bn_0'].forward(out)

            out = F.leaky_relu(out)

            self.layer_dict['pool_0'] = nn.MaxPool2d(kernel_size=3, stride=2, padding=1, ceil_mode=False)
            out = self.layer_dict['pool_0'].forward(out)

        return out

    def forward(self, x):
        out = x

        if self.small_inputs:
            out = self.layer_dict['conv_0'].forward(out)
        else:
            out = self.layer_dict['conv_0'].forward(out)
            out = self.layer_dict['bn_0'].forward(out)
            out = F.leaky_relu(out)
            out = self.layer_dict['pool_0'].forward(out)

        return out

    def reset_parameters(self):
        """
        Re-initialize the network parameters.
        """
        for item in self.layer_dict.children():
            try:
                item.reset_parameters()
            except:
                pass


class SqueezeExciteLayer(nn.Module):
    def __init__(self, input_shape, reduction=16, use_bias=False):
        super(SqueezeExciteLayer, self).__init__()

        self.input_shape = input_shape
        self.reduction = reduction
        self.channels = self.input_shape[1]
        self.use_bias = use_bias
        self.layer_dict = nn.ModuleDict()

        # build the network
        self.build_module()

    def build_module(self):
        print("Building Squeeze_Excite_Layer with in and out shape %s and reduction factor %d" % (
        self.input_shape, self.reduction))

        x = torch.zeros(self.input_shape)

        self.layer_dict['se_global_avg_pool'] = nn.AdaptiveAvgPool2d(1)
        self.layer_dict['se_fc'] = nn.Sequential(
            nn.Linear(self.channels, self.channels // self.reduction, bias=self.use_bias),
            nn.leaky_relu(inplace=True),
            nn.Linear(self.channels // self.reduction, self.channels, bias=self.use_bias),
            nn.Sigmoid()
        )

        w = self.layer_dict['se_global_avg_pool'] \
            .forward(x) \
            .view(self.input_shape[0], self.input_shape[1])
        w = self.layer_dict['se_fc'].forward(w) \
            .view(self.input_shape[0], self.input_shape[1], 1, 1) \
            .expand_as(x)

        out = torch.mul(x, w)

        return out

    def forward(self, x):
        w = self.layer_dict['se_global_avg_pool'] \
            .forward(x) \
            .view(x.shape[0], x.shape[1])
        w = self.layer_dict['se_fc'].forward(w) \
            .view(x.shape[0], x.shape[1], 1, 1) \
            .expand_as(x)

        out = torch.mul(x, w)

        return out

    def reset_parameters(self):
        """
        Re-initialize the network parameters.
        """
        for item in self.layer_dict.children():
            try:
                item.reset_parameters()
            except:
                pass
