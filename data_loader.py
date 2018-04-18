import os
import csv
import numpy as np
import cv2
import pickle
from image_processor import process_image
from sklearn.utils import shuffle
from tqdm import tqdm
import matplotlib as mpl
mpl.use('Agg')
import matplotlib.pyplot as plt

class DataLoader():
    """
    The class is used to load and process the data collected through the simulator.

    Reads the CSV file generated by the simulator and creates two arrays with the names
    of the image and the respective measurements (steering angle, throttle and break force).

    Optionally extends the images with right and left cameras view applying a correction to
    the measured angle.

    Optionally normalizes the dataset to cut off spikes of data.

    Optionally extends the dataset flipping the images horizontally (and inverting the angle)
    
    """

    def __init__(self, train_file, log_file, img_folder,
                 path_separator = '\\',
                 angle_correction = 0.1, 
                 normalize_factor = 2.5,
                 flip_min_angle = 0.0):
        """
        Initializes the data loader with the given paths to use in order to generate
        the extended dataset.

        Parameters
            train_file: The path where the final pickle file generated is saved
            log_file: The path to the log file generated by the simulator
            img_folder: The path where the images referenced in the log file are stored
            angle_correction: Optional, if supplied the left and right cameras images are read from
                              the log file and added to the dataset, applying the given correction angle
            normalize_factor: Optional, Cuts off from the dataset the spikes that go over a certain factor of the mean
            flip_min_angle: Optional, if supplied extends the dataset applying horizontal flipping to the images.
                            The value specifies the min steering angle for which the image is flipped (e.g. a value of
                            0 will flip all the images, a value of 0.2 flips the images where the steering angle is more than
                            0.2 or -0.2)
        """
        self.train_file = train_file
        self.log_file = log_file
        self.img_folder = img_folder
        self.path_separator = path_separator
        self.angle_correction = angle_correction
        self.normalize_factor = normalize_factor
        self.flip_min_angle = flip_min_angle

    def load_dataset(self, regenerate = False):
        if regenerate or not os.path.isfile(self.train_file):
            print('Processing data...')
            images, measurements = self._process_data()
            self._save_pickle(images, measurements)
        else:
            print('Training file exists, loading...')
            images, measurements = self._read_pickle()
        
        return images, measurements
    
    def generator(self, images, measurements, batch_size = 64):
        
        num_samples = len(images)
        
        assert(num_samples == len(measurements))
        
        while True:
            images, measurements = shuffle(images, measurements)
            for offset in range(0, num_samples, batch_size):
                images_batch = images[offset:offset + batch_size]
                measurements_batch = measurements[offset:offset + batch_size]
                
                X_batch = np.array(list(map(self._load_image, images_batch)))
                Y_batch = measurements_batch[:,0] # Takes the steering angle only, for now
                
                yield X_batch, Y_batch

    def plot_distribution(self, data, title, bins = 'auto', save_path = None, show = False):
        fig = plt.figure(figsize = (15, 6))
        plt.hist(data, bins = bins)
        plt.title(title)
        fig.text(0.9, 0.9, '{} measurements'.format(len(data)),
                verticalalignment='top', 
                horizontalalignment='center',
                color = 'black', fontsize = 12)
        plt.tight_layout()
        if save_path:
            plt.savefig(save_path)
        if show:
            plt.show()

    def _load_image(self, image_file):
        img = cv2.imread(os.path.join(self.img_folder, image_file))
        img = process_image(img)
        return img
   
    def _process_data(self):
        
        images, measurements = self._load_data_log()

        if self.normalize_factor is not None:
            images, measurements = self._normalize(images, measurements)

        if self.flip_min_angle is not None:
            images, measurements = self._flip_images(images, measurements)
        
        return images, measurements

    def _load_data_log(self):
        
        images = []
        measurements = []

        with open(self.log_file) as csvfile:
            reader = csv.reader(csvfile)
            for line in tqdm(reader, unit = ' lines', desc = 'CSV Processing'):
                line_images, line_measurements = self._parse_line(line)

                images.extend(line_images)
                measurements.extend(line_measurements)
                
        return np.array(images), np.array(measurements)

    def _parse_line(self, line):

        images = []
        measurements = []

        center_img, left_img, right_img = [img.split(self.path_separator)[-1] for img in line[0:3]]
        steering_angle, throttle, break_force = [float(value) for value in line[3:6]]

        # Center image
        images.append(center_img)
        measurements.append((steering_angle, throttle, break_force))

        if self.angle_correction is not None:
            # Left image
            images.append(left_img)
            measurements.append((steering_angle + self.angle_correction, throttle, break_force))
            # Right image
            images.append(right_img)
            measurements.append((steering_angle - self.angle_correction, throttle, break_force))
            # Clips the angles to the right interval (-1, 1)
            measurements = np.clip(measurements, a_min = -1.0, a_max = 1.0)

        return images, measurements

    def _normalize(self, images, measurements):
        angles = measurements[:,0]
        values, bins = np.histogram(angles, bins = 'auto')
        max_wanted = (np.mean(values) * self.normalize_factor).astype('uint32')

        drop = []

        for i, bin_right in enumerate(bins[1:]):
            bin_left = bins[i]
            if i == (len(bins) - 2):
                # Includes the right angle for the last bin
                bin_angles = np.where((angles >= bin_left) & (angles <= bin_right))
            else:
                bin_angles = np.where((angles >= bin_left) & (angles < bin_right))
            if (len(bin_angles[0]) > max_wanted):
                drop_idx = np.random.choice(bin_angles[0], size = len(bin_angles[0]) - max_wanted, replace = False)
                drop.extend(drop_idx)

        norm_images = np.delete(images, drop, axis = 0)
        norm_measurements = np.delete(measurements, drop, axis = 0)

        return norm_images, norm_measurements

    def _flip_images(self, images, measurements):
        
        new_images = []
        new_measurements = []
        
        for image, measurement in zip(tqdm(images, unit=' images', desc='Flipping'), measurements):
            steering_angle, throttle, break_force = measurement
            if steering_angle >= self.flip_min_angle or steering_angle <= -self.flip_min_angle:
                img_filpped_name = 'flipped_' + image
                img_flipped_path = os.path.join(self.img_folder, img_filpped_name)
                # if the images has been flipped already no need to reprocess it
                if not os.path.isfile(img_flipped_path):
                    img_path = os.path.join(self.img_folder, image)
                    img = cv2.imread(img_path)
                    img_flipped = cv2.flip(img, 1)
                    cv2.imwrite(img_flipped_path, img_flipped)
                new_images.append(img_filpped_name)
                new_measurements.append((-steering_angle, throttle, break_force))
        
        images_out = np.append(images, new_images, axis = 0)
        measurements_out = np.append(measurements, new_measurements, axis = 0)
                            
        return images_out, measurements_out

    def _read_pickle(self):
        with open(self.train_file, mode='rb') as f:
            train = pickle.load(f)
        return train['images'], train['measurements']

    def _save_pickle(self, images, measurements):
        results = {
            'images': images,
            'measurements': measurements
        }
        with open(self.train_file, 'wb') as f:   
            pickle.dump(results, f, protocol = pickle.HIGHEST_PROTOCOL)

