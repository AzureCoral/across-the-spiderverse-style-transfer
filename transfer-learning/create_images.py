import cv2

def create_images(path: str, save_path: str, start_time: str, end_time: str, num_imgs: int = 10):
    """
    Function that splits a video into several frames based on the num_imgs parameter:

    Parameters:
        path: str: path to the video
        save_path: str: path to save the images
        start_time: int: start time of the video
        end_time: int: end time of the video
        num_imgs: int: number of frames to split the video into

    Returns:
        None

    """
    video = cv2.VideoCapture(path)

    start_time_sec = convert_time_to_sec(start_time)
    end_time_sec = convert_time_to_sec(end_time)

    video.set(cv2.CAP_PROP_POS_MSEC, start_time_sec*1000)
    sampling_rate = (end_time_sec-start_time_sec)/num_imgs

    out_img_count = 0
    curr_time = start_time_sec

    while out_img_count < num_imgs and curr_time < end_time_sec:
        video.set(cv2.CAP_PROP_POS_MSEC, out_img_count*sampling_rate*1000+start_time_sec*1000)
        success, image = video.read()
        if success:
                cv2.imwrite(f"{save_path}/frame{out_img_count}.jpg", image)

        out_img_count += 1
        curr_time += sampling_rate

    video.release()


def convert_time_to_sec(time: str) -> int:
    """
    Helper function that takes in a string corresponding to the time in the video
    and converts the time to seconds

    Parameters:
        time: str: time in the format HH:MM:SS

    Returns:
        int: time in seconds
    """

    hrs, mins, sec = time.split(":")
    return int(hrs)*3600+int(mins)*60+int(sec)


if __name__ == "__main__":
    path = "start_path"
    save_path = "data/gwen_universe"
    start_time = "00:02:43"
    end_time = "00:09:06"
    num_imgs = 10

    create_images(path, save_path, start_time, end_time, num_imgs)

