# CSMPPI 2d quadrotor test script

import numpy as np
from costFunctions.costfun import LinBaselineCost, LinBaselineSoftCost
from costFunctions.costfun import QuadHardCost, QuadSoftCost, QuadSoftCost2
from costFunctions.costfun import QuadObsCost, QuadPosCost

from sysDynamics.sysdyn import integratorDyn, car_dynamics
from sysDynamics.sysdyn import rk4

from controllers.MPPI import MPPI, MPPI_thread, MPPI_pathos
from controllers.LinCovSteer import linCovSteer
from controllers.LQG import LQG

from Plotting.plotdata import plot_circle
from Plotting.plotdata import plot_quad

from matplotlib import pyplot as plt

from pdb import set_trace
from tqdm import tqdm
import argparse
import os


def main():
    parser = argparse.ArgumentParser(
        "Covariance Steering MPPI for 2d " + "quadrotor obstacle avoidance "
    )
    parser.add_argument(
        "-mu", help="Mu parameter for MPPI, default=0.1", default=0.01, type=float
    )
    parser.add_argument(
        "-nu",
        default=0.1,
        type=float,
        help="Nu parameter for Sampling "
        + "with higher variance default=1., pick >=1.",
    )
    parser.add_argument(
        "-K", help="MPPI sample size parameter. default=200", default=200, type=int
    )
    parser.add_argument("-T", help="MPPI horizon parameter", default=25, type=int)
    parser.add_argument("-Tsim", help="Simulation Time steps", default=200, type=int)
    parser.add_argument(
        "-lambda",
        dest="LAMBDA",
        default=0.1,
        type=float,
        help="Cost Function Parameter lambda default=0.1",
    )
    parser.add_argument(
        "-dt", type=float, default=0.05, help="Discrete time step. Default dt=0.05"
    )
    parser.add_argument(
        "-Rexit",
        type=float,
        default=5.0,
        help="Simulation exit limits if sqrt(px**2 + py**2)"
        + ">= Rexit, then the simulation is terminated. "
        + "Default=5.",
    )
    parser.add_argument(
        "-seed", type=int, default=100, help="Random Number Generator Seed"
    )
    parser.add_argument(
        "-no-noise",
        default=False,
        action="store_true",
        dest="nonoise",
        help="Flag to simulate without noise on the input",
    )
    parser.add_argument(
        "-add-noise",
        type=float,
        default=0.0,
        dest="addnoise",
        help="additional noise to the system",
    )
    parser.add_argument(
        "-paramfile",
        default="./track_params/track_params1.txt",
        help="parameters file directory for simulations",
    )
    parser.add_argument(
        "-filename", type=str, default=None, help="Directory to save results"
    )
    parser.add_argument(
        "-qmult",
        type=float,
        default=1.0,
        help="Multiplier of state cost function default",
    )
    parser.add_argument(
        "-des-speed", dest="des_speed", type=float, help="desired speed, default:3.0"
    )
    parser.add_argument(
        "-cost",
        type=str,
        default="hard",
        choices=["hard", "soft"],
        help="Cost Type. Default:sep, " + "options: hard, soft",
    )
    args = parser.parse_args()

    mu = args.mu
    NU_MPPI = args.nu
    K = args.K
    T = args.T
    iteration = args.Tsim
    dt = args.dt
    lambda_ = args.LAMBDA
    seed = args.seed
    ADD_NOISE = args.addnoise
    Q_MULT = args.qmult
    DES_SPEED = args.des_speed
    Rexit = args.Rexit
    COST_TYPE = args.cost

    np.random.seed(seed)

    FILENAME = args.filename

    PARAMFILE = args.paramfile
    if os.path.exists(PARAMFILE):
        with open(PARAMFILE) as f:
            filelist = f.readlines()

        for line in filelist:
            if "Natural System Noise Parameter" in line:
                mu = float(line.split(":")[1])
            elif "Control Sampling Covariance Parameter" in line:
                NU_MPPI = float(line.split(":")[1])
            elif "Number of Samples" in line:
                K = int(line.split(":")[1])
            elif "MPC Horizon" in line:
                T = int(line.split(":")[1])
            elif "Number of Simulation Timesteps" in line:
                iteration = int(line.split(":")[1])
            elif "Discretization time-step" in line:
                dt = float(line.split(":")[1])
            elif "Control Cost Parameter" in line:
                lambda_ = float(line.split(":")[1])
            elif "Random Number Generator" in line:
                seed = int(line.split(":")[1])
            elif "Q Multiplier" in line:
                Q_MULT = float(line.split(":")[1])
            elif "Additional Noise" in line:
                ADD_NOISE = float(line.split(":")[1])
            elif "Cost Type" in line:
                COST_TYPE = line.split(":")[1].replace(" ", "").replace("\n", "")
            elif "Desired Speed" in line:
                DES_SPEED = float(line.split(":")[1])

    x0 = np.array([[2.0], [0.0], [0.0], [0.0]])
    theta_0 = np.pi * np.random.rand() - np.pi / 2.0
    x0[0:2] = 2 * np.array([[np.cos(theta_0)], [np.sin(theta_0)]])
    x0[2] = theta_0 + np.pi / 2.0

    Sigma = mu * np.eye(2)
    Sigmainv = np.linalg.inv(Sigma)
    Ubar = np.ones((2, T))

    F = lambda x, u: car_dynamics(x, u)

    # obs_list = np.load(OBS_FILE, allow_pickle=True)

    # print(COST_TYPE)
    if COST_TYPE == "hard":
        C = lambda x: Q_MULT * LinBaselineCost(x, vdes=DES_SPEED)
        Phi = lambda x: 0.0
    elif COST_TYPE == "soft":
        C = lambda x: Q_MULT * LinBaselineSoftCost(x, vdes=DES_SPEED)
        Phi = lambda x: 0.0
    else:
        print("Undefined Cost Function!!")
        exit()

    Wk = np.eye(4) * dt
    Wk[0:2, 0:2] = np.zeros((2, 2))
    Wk = Wk * ADD_NOISE

    Xreal = []
    Ureal = []
    Xreal.append(x0)
    xk = x0
    total_cost = 0.0
    Unom, U = Ubar, Ubar
    for i in tqdm(range(iteration), disable=False):
        X, U, Sreal = MPPI_pathos(
            xk,
            F,
            K,
            T,
            Sigma,
            Phi,
            C,
            lambda_,
            U,
            Nu_MPPI=NU_MPPI,
            dt=dt,
            progbar=False,
        )

        eps = np.random.multivariate_normal(np.zeros(2), np.eye(2), (1,)).T * mu

        wk = np.random.multivariate_normal(np.zeros(4), Wk, (1,)).T

        uk = U[:, 0:1]
        xkp1 = xk + F(xk, uk + eps) * dt + wk

        Xreal.append(xkp1)
        Ureal.append(uk)

        xk = xkp1

        Udummy = np.zeros(U.shape)
        Udummy[:, 0:-1] = U[:, 1:]
        Udummy[:, -1:] = U[:, -2:-1]
        U = Udummy

        Rkp1 = np.linalg.norm(xkp1[0:2], 2)
        total_cost += (C(xk) + (lambda_ / 2.0) * (uk.T @ Sigmainv @ uk)) * dt
        if Rkp1 >= Rexit:
            print("Major Violation of Safety, Simulation Ended prematurely")
            break

    X = np.block([Xreal])
    Xpos = X[0:2, :]
    Xvel = X[2:, :]
    Vvst = np.sqrt(np.sum(np.square(Xvel), 0))
    Vmean = np.mean(Vvst)
    U = np.block([Ureal])
    Uxvst, Uyvst = U[0:1, :].squeeze(), U[1:2, :].squeeze()

    # figtraj, axtraj = plot_quad(X, obs_list, DES_POS)
    figtraj, axtraj = plot_circle(X)

    fig2, ax2 = plt.subplots()
    ax2.plot(Vvst)
    ax2.title.set_text("V vs t")

    fig3, (ax3, ax4) = plt.subplots(2)
    ax3.plot(Uxvst)
    ax3.title.set_text("$u_{x}$ vs t")
    ax4.plot(Uyvst)
    ax4.title.set_text("$u_{y}$ vs t")

    paramslist = []
    # paramslist.append('Smooth Cost with Wpos:{} and Wvel:{}'.format(Wpos, Wvel) if SOFTCOST else 'Sparse Cost')
    paramslist.append("Standard MPPI")
    paramslist.append("------------------------")
    paramslist.append("Natural System Noise Parameter, mu : {}".format(mu))
    paramslist.append("Control Sampling Covariance Parameter, nu : {}".format(NU_MPPI))
    paramslist.append("Number of Samples, K : {}".format(K))
    paramslist.append("MPC Horizon, T : {}".format(T))
    paramslist.append(
        "Number of Simulation Timesteps, iteration : {}".format(iteration)
    )
    paramslist.append("Discretization time-step, dt : {}".format(dt))
    paramslist.append("Control Cost Parameter, Lambda : {}".format(lambda_))
    paramslist.append("Random Number Generator, seed : {}".format(seed))
    paramslist.append("Q Multiplier : {}".format(Q_MULT))
    paramslist.append("Cost Type : {}".format(COST_TYPE))
    paramslist.append("Additional Noise Parameter, W : {}".format(ADD_NOISE))
    paramslist.append("Desired Speed : {}".format(DES_SPEED))
    paramslist.append("-------RESULTS-------")
    paramslist.append("Total Cost : {:.2f}".format(float(total_cost)))
    paramslist.append(
        "Average Cost : {:.2f}".format(float(total_cost / (iteration * dt)))
    )
    paramslist.append("Average Speed : {:.2f}".format(Vmean))

    if FILENAME is None:
        print("\n".join(paramslist))
        plt.show()
    elif type(FILENAME) is str:
        if not os.path.exists(FILENAME):
            os.system("mkdir {}".format(FILENAME))
        np.save(FILENAME + "/X.npy", X)
        # np.save(FILENAME + '/obs_list.npy', obs_list)
        figtraj.savefig(FILENAME + "/fig_traj.pdf")
        fig2.savefig(FILENAME + "/fig_v.pdf")
        fig3.savefig(FILENAME + "/fig_u.pdf")

        with open(FILENAME + "/params.txt", "w+") as f:
            f.write("\n".join(paramslist) + "\n")

    else:
        pass

    pass


if __name__ == "__main__":
    main()
