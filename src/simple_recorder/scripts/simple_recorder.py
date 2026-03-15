#!/usr/bin/env python3

import rospy, csv, os, json
from std_msgs.msg import String


class Recorder:
    def __init__(self):
        self.file_storage_path = str(rospy.get_param("~file_storage_path"))
        self.init()
        self.wall_start_time = rospy.Time.now()
        self.record_csv_sub = rospy.Subscriber(
            "/record_csv", String, self.record_csv_cb
        )
        self.record_jsonl_sub = rospy.Subscriber(
            "/record_jsonl", String, self.record_jsonl_cb
        )

    def init(self):
        if not os.path.exists(self.file_storage_path):
            os.makedirs(self.file_storage_path)
        else:
            for file in os.listdir(self.file_storage_path):
                if file.endswith(".csv") or file.endswith(".jsonl"):
                    os.remove(self.file_storage_path + "/" + file)

    def record_csv_cb(self, msg: String):
        # record message format: "filename,data_1,data_2,..."
        try:
            msg_list = msg.data.split(",")
            filename = msg_list[0]
            time = rospy.Time.now().to_sec() - self.wall_start_time.to_sec()
            data = msg_list[1:]
            with open(self.file_storage_path + "/" + filename + ".csv", "a") as f:
                writer = csv.writer(f)
                writer.writerow([time] + data)
        except Exception as e:
            rospy.logerr(f"Failed to record csv: {e}")

    def record_jsonl_cb(self, msg: String):
        # record message format: "{json_obj}"
        try:
            json_obj = json.loads(msg.data)
            filename = json_obj.get("filename", "default")
            time = rospy.Time.now().to_sec() - self.wall_start_time.to_sec()
            json_obj["timestamp"] = time
            with open(
                self.file_storage_path + "/" + filename + ".jsonl",
                "a",
                encoding="utf-8",
            ) as f:
                f.write(json.dumps(json_obj, ensure_ascii=False) + "\n")
        except Exception as e:
            rospy.logerr(f"Failed to record jsonl: {e}")


if __name__ == "__main__":
    rospy.init_node("recorder", anonymous=True)
    recorder = Recorder()
    rospy.spin()
