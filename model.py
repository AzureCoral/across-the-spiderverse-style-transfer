import tensorflow as tf
import platform
from helpers import tensor_to_image, avg_gram, plot_losses
import imageio
from typing import Any, List, Dict, Tuple
import time
from transfer_learning import TransferCNN

def clip_0_1(image: tf.Tensor) -> tf.Tensor:
    """
    Clips tensor values between 0 and 1.

    Parameters:
    image (tf.Tensor): The tensor to clip.

    Returns:
    tf.Tensor: The clipped tensor.
    """
    return tf.clip_by_value(image, clip_value_min=0.0, clip_value_max=1.0)

def mse(x: tf.Tensor, y: tf.Tensor) -> tf.Tensor:
    """
    Calculates the mean squared error between two tensors.

    Parameters:
    x (tf.Tensor): The first tensor.
    y (tf.Tensor): The second tensor.

    Returns:
    tf.Tensor: The mean squared error between x and y.
    """
    return tf.reduce_mean((x - y)**2)

def vgg_layers_pretrained(layer_names: List[str]) -> tf.keras.Model:
    """
    Creates a VGG model that returns a list of intermediate output values.

    Parameters:
    layer_names (List[str]): The names of the layers to include in the model.

    Returns:
    tf.keras.Model: The resulting VGG model.
    """
    vgg = tf.keras.applications.VGG19(include_top=False, weights='imagenet')
    vgg.trainable = False

    outputs = [vgg.get_layer(name).output for name in layer_names]

    model = tf.keras.Model([vgg.input], outputs)

    return model

def vgg_layers_custom(layer_names: List[str]) -> tf.keras.Model:
    """
    Creates a VGG model that returns a list of intermediate output values.

    Parameters:
    layer_names (List[str]): The names of the layers to include in the model.

    Returns:
    tf.keras.Model: The resulting VGG model.
    """
    model = TransferCNN(layer_names)
    loaded_model = tf.keras.models.load_model(
        'checkpoints/weights_trained.keras',
        custom_objects={'TransferCNN': lambda trainable_layers, load=False: TransferCNN(trainable_layers=trainable_layers, load=load)}
    )

    loaded_model = loaded_model.vgg

    # Assuming the input layer is the first layer
    input_layer = loaded_model.input

    for layer in loaded_model.layers:
        layer.trainable = False

    loaded_model.summary()

    outputs = [loaded_model.get_layer(name).output for name in layer_names]

    model = tf.keras.Model(inputs=input_layer, outputs=outputs)

    return model

def gram_matrix(input_tensor: tf.Tensor) -> tf.Tensor:
    """
    Calculates the Gram matrix for a given tensor.

    Parameters:
    input_tensor (tf.Tensor): The tensor to calculate the Gram matrix of.

    Returns:
    tf.Tensor: The resulting Gram matrix.
    """
    #performing element-wise multiplication and summation along the first three axis of the input tensor
    outer_product = tf.linalg.einsum('bijc,bijd->bcd', input_tensor, input_tensor)

    #finding the dimensions of the collapsed dimensions
    input_shape = tf.shape(input_tensor)
    num_locations = tf.cast(input_shape[1] * input_shape[2], tf.float32)

    #sort of averaging the summed product taken along the 2nd and 3rd dimensions
    normalized_result = outer_product / num_locations

    return normalized_result

def calculate_loss(outputs: Dict[str, tf.Tensor], targets: Dict[str, tf.Tensor], weight: float) -> tf.Tensor:
    """
    Calculates the loss.

    Parameters:
    outputs (Dict[str, tf.Tensor]): The outputs.
    targets (Dict[str, tf.Tensor]): The target values.
    weight (float): The weight of the loss.

    Returns:
    tf.Tensor: The loss.
    """
    num_layers = len(targets)
    loss = tf.add_n([mse(output, targets[name]) for name, output in outputs.items()])
    loss /= num_layers
    loss *= weight
    return loss

class StyleContentModel(tf.keras.models.Model):
    def __init__(self, style_layers: List[str], content_layers: List[str]):
        """
        Initializes the StyleContentModel.

        Parameters:
        style_layers (List[str]): The names of the style layers to include in the model.
        content_layers (List[str]): The names of the content layers to include in the model.
        """
        super(StyleContentModel, self).__init__()
        try:
            self.vgg = vgg_layers_custom(style_layers + content_layers)
        except IOError:
            self.vgg = vgg_layers_pretrained(style_layers + content_layers)
        self.style_layers = style_layers
        self.content_layers = content_layers
        self.num_style_layers = len(style_layers)
        self.vgg.trainable = False

    def call(self, inputs: tf.Tensor) -> Tuple[Dict[str, tf.Tensor], Dict[str, tf.Tensor]]:
        """
        Calls the StyleContentModel.

        Parameters:
        inputs (tf.Tensor): The input tensor.

        Returns:
        Dict[str, Dict[str, tf.Tensor]]: A dictionary containing the style and content outputs.
        """
        "Expects float input in [0,1]"
        inputs = 255.0 * inputs
        preprocessed_input = tf.keras.applications.vgg19.preprocess_input(inputs)
        outputs = self.vgg(preprocessed_input)

        style_outputs, content_outputs = (outputs[:self.num_style_layers], 
                    outputs[self.num_style_layers:])

        style_outputs = [gram_matrix(style_output) 
            for style_output in style_outputs]

        content_dict = {content_name: value for content_name, value 
            in zip(self.content_layers, content_outputs)}

        style_dict = {style_name: value for style_name, value 
            in zip(self.style_layers, style_outputs)}

        return content_dict, style_dict

class StyleTransfer():
    def __init__(
        self, 
        style_layers: List[str],
        content_layers: List[str],
        style_images: List[tf.Tensor],
        content_image: tf.Tensor,
        style_weight: float = 1e-2,
        content_weight: float = 1e4,
        total_variation_weight: float = 100):
        """
        Initializes the StyleTransfer.

        Parameters:
        style_layers (List[str]): The names of the style layers to include in the model.
        content_layers (List[str]): The names of the content layers to include in the model.
        style_image (tf.Tensor): The style image tensor.
        content_image (tf.Tensor): The content image tensor.
        style_weight (float): The weight of the style loss.
        content_weight (float): The weight of the content loss.

        """
        self.extractor = StyleContentModel(style_layers, content_layers)

        self.style_targets = {}
        for layer in style_layers:
            self.style_targets[layer] = []
        for style_image in style_images:
            style_target = self.extractor(style_image)[1]
            for key in style_target:
                self.style_targets[key].append(style_target[key])
        self.style_targets = avg_gram(self.style_targets)

        # img_styles = [self.extractor(style_image)[1] for style_image in style_images]
        # self.style_targets = {style_layer : tf.keras.layers.average([img[style_layer] for img in img_styles]) for style_layer in style_layers}

        self.content_targets = self.extractor(content_image)[0]
        if platform.system() == "Darwin" and platform.processor() == "arm":
            self.opt = tf.keras.optimizers.legacy.Adam(learning_rate=0.02, beta_1=0.99, epsilon=1e-1)
        else:
            self.opt = tf.keras.optimizers.Adam(learning_rate=0.02, beta_1=0.99, epsilon=1e-1)
        self.image = tf.Variable(content_image)

        self.style_weight = style_weight
        self.content_weight = content_weight
        self.total_variation_weight = total_variation_weight

    def style_loss(self, style_outputs: Dict[str, tf.Tensor]) -> tf.Tensor:
        """
        Calculates the style loss.

        Parameters:
        style_outputs (Dict[str, tf.Tensor]): The style outputs.

        Returns:
        tf.Tensor: The style loss.
        """
        return calculate_loss(style_outputs, self.style_targets, self.style_weight)

    def content_loss(self, content_outputs: Dict[str, tf.Tensor]) -> tf.Tensor:
        """
        Calculates the content loss.

        Parameters:
        content_outputs (Dict[str, tf.Tensor]): The content outputs.

        Returns:
        tf.Tensor: The content loss.
        """
        return calculate_loss(content_outputs, self.content_targets, self.content_weight)

    @tf.function()
    def train_step(self):
        with tf.GradientTape() as tape:
            content_outputs, style_outputs = self.extractor(self.image)

            content_loss = self.content_loss(content_outputs)
            style_loss = self.style_loss(style_outputs)

            loss = style_loss + content_loss + self.total_variation_weight*tf.image.total_variation(self.image)

        grad = tape.gradient(loss, self.image)
        return loss, grad, style_loss, content_loss


    def train(self, epochs: int = 60, steps_per_epoch: int = 25, visuals: bool = False) -> tf.Tensor:
        """
        Trains the model for a specified number of epochs, optionally creates visuals such as loss plots and a training GIF.

        Parameters:
        epochs (int): The number of epochs to train for.
        steps_per_epoch (int): The number of steps per epoch.

        Returns:
        tf.Tensor: The final image tensor after training.
        """
        style_losses, content_losses, image_paths = [], [], []

        epoch_len = len(str(epochs-1))
        time_start = int(time.time())

        for epoch in range(epochs):
            if visuals:
                # Save image at the end of each epoch
                output_file_path = f"outputs/gif_output/Image{time_start}_{epoch:0>{epoch_len}}.jpg"
                with open(output_file_path,'wb') as f:
                    tensor_to_image(self.image).save(f, "JPEG")
                    image_paths.append(output_file_path)

            print(f"Epoch {epoch:0>{epoch_len}}:\t", end="")
            for step in range(steps_per_epoch):
                _, grad, style_loss, content_loss = self.train_step()

                style_losses.append(style_loss)
                content_losses.append(content_loss)

                self.opt.apply_gradients([(grad, self.image)])
                self.image.assign(clip_0_1(self.image))

                print(f"\rEpoch {epoch:0>{epoch_len}}: ({step + 1}/{steps_per_epoch})", end='', flush=True)

            print(f'\tstyle loss: {style_losses[-1]:.2f}\tcontent loss: {content_losses[-1]:.2f}')


        # Create GIF
        if visuals:
            images = [imageio.imread(file_path) for file_path in image_paths]
            gif_path = f"outputs/gif_output/training_{time_start}.gif"
            imageio.mimsave(gif_path, images, fps=1)
            plot_losses(style_losses, content_losses)  # Assuming plot_losses is a predefined function

        return self.image
