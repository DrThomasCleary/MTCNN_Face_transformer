#importing libraries
from facenet_pytorch import MTCNN
import torch
from torchvision import datasets, transforms
from torch.utils.data import DataLoader
import os
import numpy as np
import time
import math
import importlib.util
import matplotlib.pyplot as plt
from torchvision.transforms import Resize


resize = Resize((112, 112))

use_mtcnn = False  # Change this to False if you want to exclude MTCNN
to_tensor = transforms.ToTensor()

if use_mtcnn:
    mtcnn = MTCNN(image_size=112, margin=24, keep_all=False, min_face_size=50)
else:
    mtcnn = None

# Import the 'perform_val' function from the 'util.utils' module
util_path = "/Users/br/Software/Machine_learning/Face-Transformer/util/utils.py"
spec = importlib.util.spec_from_file_location("util.utils", util_path)
utils_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils_module)
perform_val = utils_module.perform_val

vits_face_path = "/Users/br/Software/Machine_learning/Face-Transformer/vit_pytorch/vits_face.py"
spec = importlib.util.spec_from_file_location("vits_face", vits_face_path)
vits_face_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vits_face_module)
ViTs_face = vits_face_module.ViTs_face

# Initialize the ViT_face model
model = ViTs_face(
    image_size=112,
    patch_size=8,
    loss_type='CosFace',
    GPU_ID=torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu'),
    num_class=93431,
    dim=512,
    depth=20,
    heads=8,
    pad = 2,
    ac_patch_size = 8,
    mlp_dim=2048,
    dropout=0.1,
    emb_dropout=0.1
)

# Load the pre-trained weights
checkpoint_path = "/Users/br/Software/Machine_learning/MTCNN_face_transformer/pretrained_models/Backbone_VIT_Epoch_2_Batch_20000_Time_2021-01-12-16-48_checkpoint.pth"
model.load_state_dict(torch.load(checkpoint_path, map_location=torch.device('cpu')))

# Set the model to evaluation mode
model.eval()


# initializing MTCNN and InceptionResnetV1 
mtcnn = MTCNN(image_size=112, margin=24, keep_all=False, min_face_size=50)

# load the dataset
matched_dataset = datasets.ImageFolder('/Users/br/Software/Machine_learning/MTCNN_face_transformer/LFW_dataset/small_samples/matched_faces_test')
matched_loader = DataLoader(matched_dataset, collate_fn=lambda x: x[0])

mismatched_dataset = datasets.ImageFolder('/Users/br/Software/Machine_learning/MTCNN_face_transformer/LFW_dataset/small_samples/mismatched_faces_test')
mismatched_dataset.idx_to_class = {i: c for c, i in mismatched_dataset.class_to_idx.items()}
mismatched_loader = DataLoader(mismatched_dataset, collate_fn=lambda x: x[0])

def calculate_accuracy(labels, distances, threshold):
    correct_predictions = 0
    total_predictions = len(labels)

    for i in range(len(distances)):
        if labels[i] == 1 and distances[i] <= threshold:
            correct_predictions += 1
        if labels[i] == 0 and distances[i] > threshold:
            correct_predictions += 1

    accuracy = correct_predictions / total_predictions
    return accuracy

def calculate_far_frr(labels, distances, threshold):
    num_positive = np.sum(labels)
    num_negative = len(labels) - num_positive

    false_accepts = 0
    false_rejects = 0

    for i in range(len(distances)):
        if labels[i] == 1 and distances[i] > threshold:
            false_rejects += 1
        if labels[i] == 0 and distances[i] <= threshold:
            false_accepts += 1

    FAR = false_accepts / num_negative
    FRR = false_rejects / num_positive

    return FAR, FRR

def add_jitter(values, jitter_amount=0.2):
    return values + np.random.uniform(-jitter_amount, jitter_amount, len(values))

# Initialize variables to track time
resnet_time = 0
n_operations = 0

# generate embeddings for the dataset
matched_embedding_list = []
matched_name_list = []
for folder in os.listdir(matched_dataset.root):
    folder_path = os.path.join(matched_dataset.root, folder)
    if os.path.isdir(folder_path):
        # load the first two images in the folder
        images = []
        for i, filename in enumerate(sorted(os.listdir(folder_path))):
            if i >= 2:
                break
            image_path = os.path.join(folder_path, filename)
            image = datasets.folder.default_loader(image_path)
            images.append(image)
        # generate embeddings for the two images in the folder
        if len(images) == 2:
            embeddings = []
            for i in range(2):
                start_time_matched_resnet = time.time()
                resized_image = resize(images[i])
                tensor_image = to_tensor(resized_image)
                emb = model(tensor_image.unsqueeze(0))
                embeddings.append(emb.detach())
                elapsed_time_matched_resnet = time.time() - start_time_matched_resnet
                resnet_time += elapsed_time_matched_resnet
                n_operations += 1
            if len(embeddings) == 2:
                matched_embedding_list.extend(embeddings)
                matched_name_list.extend([folder] * 2)
            else:
                print(f"Not enough faces detected in {folder_path}")

            

# generate embeddings for the dataset
mismatched_embedding_list = []
mismatched_name_list = []
for image, index in mismatched_loader:
    start_time__mismatched_resnet = time.time()
    resized_image = resize(image)
    tensor_image = to_tensor(resized_image)
    emb = model(tensor_image.unsqueeze(0))
    mismatched_embedding_list.append(emb.detach())  
    mismatched_name_list.append(mismatched_dataset.idx_to_class[index]) 
    elapsed_time_mismatched_resnet = time.time() - start_time__mismatched_resnet
    resnet_time += elapsed_time_mismatched_resnet
    n_operations += 1


if len(mismatched_embedding_list) % 2 != 0:
    mismatched_embedding_list.pop()
    mismatched_name_list.pop()


dist_matched = [torch.dist(matched_embedding_list[i], matched_embedding_list[i + 1]).item() for i in range(0, len(matched_embedding_list), 2)]
dist_mismatched = [torch.dist(mismatched_embedding_list[i], mismatched_embedding_list[i + 1]).item() for i in range(0, len(mismatched_embedding_list), 2)]

distances = dist_matched + dist_mismatched
labels = [1] * len(dist_matched) + [0] * len(dist_mismatched)

accuracies = []
thresholds = np.linspace(0.1, 1.6, 5000)
FARs = []
FRRs = []
for threshold in thresholds:
    FAR, FRR = calculate_far_frr(labels, distances, threshold)
    accuracy = calculate_accuracy(labels, distances, threshold)
    FARs.append(FAR)
    FRRs.append(FRR)
    accuracies.append(accuracy)

max_accuracy_index = np.argmax(accuracies)
max_accuracy_threshold = thresholds[max_accuracy_index]
max_accuracy = accuracies[max_accuracy_index]
eer_index = np.argmin(np.abs(np.array(FARs) - np.array(FRRs)))
eer = (FARs[eer_index] + FRRs[eer_index]) / 2
print("EER:", eer)

# Calculate the accuracy and F1 score of the model
true_matched = []
true_mismatched = []
pred_matched = []
pred_mismatched = []

# Compare embeddings and calculate metrics for matched faces
for i in range(0, len(matched_embedding_list), 2):
    emb1 = matched_embedding_list[i]
    emb2 = matched_embedding_list[i + 1]
    dist = torch.dist(emb1, emb2).item()
    is_match = matched_name_list[i] == matched_name_list[i + 1]
    true_matched.append(is_match)
    pred_matched.append(dist < max_accuracy_threshold)

# Compare embeddings and calculate metrics for mismatched faces
for i in range(0, len(mismatched_embedding_list), 2):
    emb1 = mismatched_embedding_list[i]
    emb2 = mismatched_embedding_list[i + 1]
    dist = torch.dist(emb1, emb2).item()
    is_mismatch = mismatched_name_list[i] != mismatched_name_list[i + 1]
    true_mismatched.append(is_mismatch)
    pred_mismatched.append(dist > max_accuracy_threshold)

# True positives
matched_correctly = 0
dist_matched_correctly = []
for dist, same_face, pred in zip(dist_matched, true_matched, pred_matched):
    if same_face == True and pred == True:
        matched_correctly += 1
        dist_matched_correctly.append(dist)

# True negatives
mismatched_correctly = 0
dist_mismatched_correctly = []
for dist, different_face, pred in zip(dist_mismatched, true_mismatched, pred_mismatched):
    if different_face == True and pred == True:
        mismatched_correctly += 1
        dist_mismatched_correctly.append(dist)

# False positives
matched_incorrectly = 0
dist_matched_incorrectly = []
for dist, same_face, pred in zip(dist_matched, true_matched, pred_matched):
    if same_face == True and pred == False:
        matched_incorrectly += 1
        dist_matched_incorrectly.append(dist)

# False negatives
mismatched_incorrectly = 0
dist_mismatched_incorrectly = []
for dist, different_face, pred in zip(dist_mismatched, true_mismatched, pred_mismatched):
    if different_face == True and pred == False:
        mismatched_incorrectly += 1
        dist_mismatched_incorrectly.append(dist)

accuracy = (matched_correctly + mismatched_correctly) / (matched_correctly + mismatched_correctly + matched_incorrectly + mismatched_incorrectly)
precision = matched_correctly / (matched_correctly + matched_incorrectly)
recall = matched_correctly / (matched_correctly + mismatched_incorrectly)
f1 = 2 * precision * recall / (precision + recall)
pred_matched.append(dist < max_accuracy_threshold)
pred_mismatched.append(dist > max_accuracy_threshold)
average_resnet_time = resnet_time / n_operations

print("Max Accuracy Threshold:", max_accuracy_threshold)
print("Average InceptionResnetV1 time:", average_resnet_time)
print("Matched_Correctly: ", matched_correctly)
print("Mismatched_Correctly: ", mismatched_correctly)
print("Matched_Incorrectly: ", matched_incorrectly)
print("Mismatched_Incorrectly: ", mismatched_incorrectly)
print("Accuracy: ", accuracy)
print("Precision: ", precision)
print("Recall: ", recall)
print("F1 score: ", f1)

# Scatter plot
fig, ax = plt.subplots()

# Increase jitter amount
jitter_amount = 0.5

# True positives
ax.scatter(dist_matched_correctly, add_jitter([3] * len(dist_matched_correctly), jitter_amount), c='green', alpha=0.5, label='Matched_Correctly')
# True negatives
ax.scatter(dist_mismatched_correctly, add_jitter([2] * len(dist_mismatched_correctly), jitter_amount), c='blue', alpha=0.5, label='Mismatched_Correctly')
# False positives
ax.scatter(dist_matched_incorrectly, add_jitter([1] * len(dist_matched_incorrectly), jitter_amount), c='red', alpha=0.5, label='Matched_Incorrectly')
# False negatives
ax.scatter(dist_mismatched_incorrectly, add_jitter([0] * len(dist_mismatched_incorrectly), jitter_amount), c='orange', alpha=0.5, label='Mismatched_Incorrectly')

# EER threshold
ax.axvline(x=max_accuracy_threshold, color='purple', linestyle='--', label='Max_accuracy Threshold')

ax.set_xlabel('Distance')
ax.set_yticks([0, 1, 2, 3])
ax.set_yticklabels(['Mismatched_Incorrectly', 'Matched_Incorrectly', 'Mismatched_Correctly', 'Matched_Correctly'])
ax.legend()

plt.savefig('/Users/br/Software/Machine_learning/MTCNN_face_transformer/output.png')
